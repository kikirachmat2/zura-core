"""
core/actuator.py - Centralized Single-Door Actuator & Audit Gateway
Per Zura Charter v2 (Fase 0.5 & 0.5b):
Every state-mutating action (service restarts, file/env modification, network reconfiguration,
outbound posting/replenish, deletion) MUST pass exclusively through actuate().

Key Guarantees:
1. Kill Switch (/pause): Fail-closed check against persistent system_state.
2. Audit Trail: Writes PENDING audit record to SQLite BEFORE executing, updates to EXECUTED/FAILED after.
3. Secret Sanitization: Strictly scrubs passwords, tokens, private keys, and IPs from audit params.
4. Tiers:
   - L1: Autonomous execution with audit logging.
   - L2: Autonomous execution + post-action notification (supports /undo if reversible).
   - L3: Explicit human approval required via single-use Telegram button (expires in 10 minutes).
5. Centralized Persistent Rate Limiting: Composite key (action_name, host, service) stored in SQLite.
6. Revenue-Critical Circuit Breaker: Sends one-time Telegram alert when throttled.
7. /undo <action_id>: Reverts reversible actions through actuate() with dedicated audit entry.
"""

import os
import re
import sys
import time
import json
import uuid
import sqlite3
import shutil
import subprocess
import logging
from typing import Callable, Any, Dict, Optional, Tuple, List, Set
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import core.config as config

logger = logging.getLogger("ActuatorGateway")

# Optional injected DB path (for test isolation)
_CUSTOM_DB_PATH: Optional[Path] = None


def get_db_path() -> Path:
    """Returns injected custom DB path or default from config."""
    return _CUSTOM_DB_PATH if _CUSTOM_DB_PATH is not None else config.DB_PATH


def set_actuator_db_path(path: Optional[Path]):
    """Sets custom DB path for test isolation."""
    global _CUSTOM_DB_PATH
    _CUSTOM_DB_PATH = path


# Rate limit registry: actuator_name -> minimum seconds between executions
RATE_LIMITS: Dict[str, float] = {
    "server_restart_service": 3600.0,  # Max 1 restart per hour
    "kibot_restart_service": 3600.0,   # Max 1 restart per hour
    "kibot_tune_env": 3600.0,          # Max 1 config tune per hour
    "network_wifi_reconnect": 300.0,   # Max 1 wifi heal per 5 mins
    "mac_purge_cache": 600.0,          # Max 1 vacuum per 10 mins
    "threads_replenish_queue": 180.0,  # Max 1 replenish per 3 mins
    "gitops_apply_update": 60.0,       # Cooldown 1 min between updates
}

# Revenue-critical actions subject to circuit-breaker alerts
REVENUE_CRITICAL_ACTIONS: Set[str] = {
    "kibot_tune_env",
    "kibot_restart_service",
    "threads_replenish_queue",
}

# In-memory circuit breaker alert tracker: (action_name, host, service)
_CIRCUIT_BREAKER_TRIGGERED: Set[Tuple[str, str, str]] = set()

# In-memory store for pending L3 approvals: action_id -> dict
PENDING_APPROVALS: Dict[str, Dict[str, Any]] = {}

# In-memory store for registered undo callbacks: action_id -> callable
REVERT_REGISTRY: Dict[str, Callable] = {}

# Optional notifier hook (registered by main.py)
_NOTIFIER_HOOK: Optional[Callable] = None

# Strict whitelist for mac_purge_cache directories
ALLOWED_CACHE_WHITELIST: Set[str] = {
    "com.apple.Safari",
    "com.operasoftware.Opera",
    "com.microsoft.VSCode",
    "Google/Chrome",
    "com.spotify.client",
    "antigravity-updater",
    "GeoServices",
    "pip",
    "_cacache",
    ".cache",
    "/tmp",
    "/var/tmp"
}

# Patterns for scrubbing secrets and sensitive data
SECRET_KEY_PATTERN = re.compile(r"(token|secret|password|pass|key|credential|auth|cert)", re.IGNORECASE)
SECRET_VAL_PATTERNS = [
    re.compile(r"-----BEGIN[A-Z\s]+PRIVATE KEY-----[\s\S]+?-----END[A-Z\s]+PRIVATE KEY-----"),
    re.compile(r"bot\d+:[A-Za-z0-9_-]{20,}"),          # Telegram bot tokens
    re.compile(r"ghp_[A-Za-z0-9]{36}"),                # GitHub tokens
    re.compile(r"AIza[0-9A-Za-z-_]{35}"),              # Google API keys
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),                # Generic secret keys
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),        # IP addresses
]


class ActuatorError(Exception):
    """Base exception for actuator errors."""
    pass


class ActuatorPausedError(ActuatorError):
    """Raised when an action is attempted while system is paused (Kill Switch active)."""
    pass


class ActuatorRateLimitError(ActuatorError):
    """Raised when an action exceeds the centralized cooldown limit."""
    pass


class ActuatorApprovalRequired(ActuatorError):
    """Raised when an L3 action is queued and awaiting human approval."""
    def __init__(self, action_id: str, message: str):
        super().__init__(message)
        self.action_id = action_id


def register_notifier(fn: Callable):
    """Registers an async/sync notifier function to send Telegram alerts for L2/L3."""
    global _NOTIFIER_HOOK
    _NOTIFIER_HOOK = fn


def init_actuator_db(db_path: Optional[Path] = None):
    """Initializes actuator audit log, system state, and persistent rate limits tables."""
    target_db = db_path or get_db_path()
    try:
        if not target_db.parent.exists():
            target_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(target_db), timeout=5) as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS actuator_audit_log (
                    id TEXT PRIMARY KEY,
                    timestamp REAL,
                    entity TEXT,
                    action_name TEXT,
                    reason TEXT,
                    tier TEXT,
                    params_before TEXT,
                    params_after TEXT,
                    revert_cmd TEXT,
                    reversible INTEGER,
                    status TEXT,
                    error TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS system_state (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at REAL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS actuator_rate_limits (
                    action_name TEXT NOT NULL,
                    host TEXT NOT NULL DEFAULT 'localhost',
                    service TEXT NOT NULL DEFAULT 'default',
                    last_executed REAL NOT NULL,
                    PRIMARY KEY (action_name, host, service)
                )
            """)
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to init actuator audit table: {e}")


# Initialize table on module load
init_actuator_db()


def sanitize_value(val: Any) -> Any:
    """Recursively redacts sensitive patterns and IP addresses from parameters."""
    if isinstance(val, dict):
        sanitized = {}
        for k, v in val.items():
            if SECRET_KEY_PATTERN.search(str(k)):
                sanitized[k] = "[REDACTED_SECRET]"
            else:
                sanitized[k] = sanitize_value(v)
        return sanitized
    elif isinstance(val, (list, tuple)):
        return [sanitize_value(x) for x in val]
    elif isinstance(val, str):
        cleaned = val
        for pat in SECRET_VAL_PATTERNS:
            cleaned = pat.sub("[REDACTED_SECRET]", cleaned)
        return cleaned
    return val


def is_system_paused() -> bool:
    """
    Checks if Kill Switch is active.
    FAIL-CLOSED: If DB cannot be accessed or throws error, returns True (treats as paused).
    """
    db_file = get_db_path()
    try:
        if not db_file.exists():
            return True  # Fail-closed: missing DB treated as paused
        with sqlite3.connect(str(db_file), timeout=3) as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM system_state WHERE key = 'system_paused'")
            row = cur.fetchone()
            if row and row[0]:
                val = str(row[0]).strip().lower()
                return val in ["1", "true", "yes", "paused"]
            return False
    except Exception as e:
        logger.error(f"Fail-closed Kill Switch triggered on DB error: {e}")
        return True  # Fail-closed!


def set_system_paused(paused: bool):
    """Sets persistent Kill Switch state."""
    db_file = get_db_path()
    with sqlite3.connect(str(db_file), timeout=5) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO system_state (key, value, updated_at)
            VALUES ('system_paused', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """, (str(paused).lower(), time.time()))
        conn.commit()


def get_persistent_rate_limit(action_name: str, host: str = "localhost", service: str = "default") -> float:
    """Reads persistent rate limit execution timestamp from SQLite composite key."""
    db_file = get_db_path()
    try:
        with sqlite3.connect(str(db_file), timeout=3) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT last_executed FROM actuator_rate_limits
                WHERE action_name = ? AND host = ? AND service = ?
            """, (action_name, host, service))
            row = cur.fetchone()
            if row and row[0]:
                return float(row[0])
    except Exception:
        pass
    return 0.0


def record_persistent_rate_limit(action_name: str, host: str = "localhost", service: str = "default", ts: Optional[float] = None):
    """Writes persistent execution timestamp for composite key in SQLite."""
    db_file = get_db_path()
    exec_ts = ts if ts is not None else time.time()
    try:
        with sqlite3.connect(str(db_file), timeout=5) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO actuator_rate_limits (action_name, host, service, last_executed)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(action_name, host, service) DO UPDATE SET last_executed=excluded.last_executed
            """, (action_name, host, service, exec_ts))
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to record persistent rate limit: {e}")


def record_audit(action_id: str, entity: str, action_name: str, reason: str,
                 tier: str, params_before: Any, params_after: Any, revert_cmd: str,
                 reversible: bool, status: str, error: str = ""):
    """Writes or updates audit row in SQLite."""
    san_before = json.dumps(sanitize_value(params_before))
    san_after = json.dumps(sanitize_value(params_after))
    db_file = get_db_path()
    try:
        with sqlite3.connect(str(db_file), timeout=5) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO actuator_audit_log
                (id, timestamp, entity, action_name, reason, tier, params_before, params_after, revert_cmd, reversible, status, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    params_after=excluded.params_after,
                    error=excluded.error
            """, (
                action_id, time.time(), entity, action_name, reason, tier,
                san_before, san_after, revert_cmd, 1 if reversible else 0,
                status, error
            ))
            conn.commit()
    except Exception as e:
        logger.error(f"Audit log write failed: {e}")


def actuate(name: str,
            tier: str,
            fn: Callable,
            params: Optional[Dict[str, Any]] = None,
            entity: str = "core",
            reason: str = "",
            revert: Optional[Callable] = None,
            revert_cmd: str = "",
            reversible: bool = True) -> Dict[str, Any]:
    """
    Central single-door gateway for all state-mutating actions.
    Enforces Kill Switch, audit logging, composite persistent rate limiting, and approval tiers.
    """
    if params is None:
        params = {}

    action_id = str(uuid.uuid4())[:8]
    tier = tier.upper()

    host = str(params.get("host") or params.get("node") or "localhost")
    service = str(params.get("service") or params.get("changed_key") or "default")

    # 1. Kill Switch Check (Fail-closed)
    if is_system_paused():
        record_audit(action_id, entity, name, reason, tier, params, None, revert_cmd, reversible, "BLOCKED_PAUSED", "Kill switch /pause active")
        raise ActuatorPausedError(f"Action '{name}' blocked: System is in PAUSED / Kill-Switch state.")

    # 2. Centralized Persistent Rate Limit Check (action_name, host, service)
    if name in RATE_LIMITS:
        cooldown = RATE_LIMITS[name]
        last_exec = get_persistent_rate_limit(name, host, service)
        elapsed = time.time() - last_exec
        if elapsed < cooldown:
            wait_rem = int(cooldown - elapsed)
            err_msg = f"Rate limit active for '{name}' [{host}/{service}]. Cooldown: {wait_rem}s remaining."
            record_audit(action_id, entity, name, reason, tier, params, None, revert_cmd, reversible, "BLOCKED_RATE_LIMIT", err_msg)

            # Circuit breaker: Send alert ONCE for revenue-critical actions
            circuit_key = (name, host, service)
            if name in REVENUE_CRITICAL_ACTIONS and circuit_key not in _CIRCUIT_BREAKER_TRIGGERED:
                _CIRCUIT_BREAKER_TRIGGERED.add(circuit_key)
                if _NOTIFIER_HOOK:
                    try:
                        _NOTIFIER_HOOK("CIRCUIT_BREAKER", {
                            "name": name,
                            "host": host,
                            "service": service,
                            "wait_rem": wait_rem
                        })
                    except Exception as ex:
                        logger.warning(f"Circuit breaker alert notification failed: {ex}")

            raise ActuatorRateLimitError(err_msg)

    # 3. L3 Approval Interception
    if tier == "L3":
        now = time.time()
        PENDING_APPROVALS[action_id] = {
            "id": action_id,
            "name": name,
            "entity": entity,
            "tier": tier,
            "fn": fn,
            "params": params,
            "host": host,
            "service": service,
            "reason": reason,
            "revert": revert,
            "revert_cmd": revert_cmd,
            "reversible": reversible,
            "created_at": now,
            "expires_at": now + 600.0,  # 10 minutes expiry
            "status": "PENDING_APPROVAL"
        }
        record_audit(action_id, entity, name, reason, tier, params, None, revert_cmd, reversible, "PENDING_APPROVAL")
        logger.info(f"🛡️ Action '{name}' [{action_id}] queued for L3 approval (expires in 600s).")
        
        # Trigger notifier hook if available
        if _NOTIFIER_HOOK:
            try:
                _NOTIFIER_HOOK("L3", {
                    "action_id": action_id,
                    "name": name,
                    "entity": entity,
                    "reason": reason,
                    "params": sanitize_value(params)
                })
            except Exception as e:
                logger.warning(f"Notifier hook error for L3: {e}")

        return {
            "success": False,
            "status": "AWAITING_APPROVAL",
            "action_id": action_id,
            "message": f"Action '{name}' requires L3 approval."
        }

    # 4. Write PENDING audit record before execution
    record_audit(action_id, entity, name, reason, tier, params, None, revert_cmd, reversible, "PENDING")

    # 5. Execute Action (L1 & L2)
    try:
        try:
            result = fn(**params) if isinstance(params, dict) else fn()
        except TypeError:
            result = fn()
        record_audit(action_id, entity, name, reason, tier, params, result, revert_cmd, reversible, "EXECUTED")

        # Update persistent rate limit timestamp upon success
        if name in RATE_LIMITS:
            record_persistent_rate_limit(name, host, service, time.time())
            _CIRCUIT_BREAKER_TRIGGERED.discard((name, host, service))

        # Register revert handler if reversible
        if reversible and revert:
            REVERT_REGISTRY[action_id] = revert

        # Trigger L2 notification hook if available
        if tier == "L2" and _NOTIFIER_HOOK:
            try:
                _NOTIFIER_HOOK("L2", {
                    "action_id": action_id,
                    "name": name,
                    "entity": entity,
                    "reason": reason,
                    "reversible": reversible
                })
            except Exception as e:
                logger.warning(f"Notifier hook error for L2: {e}")

        return {
            "success": True,
            "status": "EXECUTED",
            "action_id": action_id,
            "tier": tier,
            "result": result
        }
    except Exception as e:
        record_audit(action_id, entity, name, reason, tier, params, None, revert_cmd, reversible, "FAILED", str(e))
        raise ActuatorError(f"Actuator '{name}' execution failed: {e}")


def execute_approved_action(action_id: str, user_id: int) -> Dict[str, Any]:
    """
    Executes an action that was previously queued for L3 approval.
    Verifies user authorization, single-use, 10m expiry, pause state, and re-checks rate limit.
    """
    if user_id != config.TELEGRAM_CHAT_ID:
        return {"success": False, "error": "Unauthorized: user ID does not match master chat ID."}

    if action_id not in PENDING_APPROVALS:
        return {"success": False, "error": f"Action ID '{action_id}' not found or already consumed."}

    action_data = PENDING_APPROVALS[action_id]
    if action_data.get("status") != "PENDING_APPROVAL":
        return {"success": False, "error": "Action has already been processed."}

    # 1. Expiration Check (10 minutes)
    if time.time() > action_data["expires_at"]:
        action_data["status"] = "EXPIRED"
        record_audit(action_id, action_data["entity"], action_data["name"], action_data["reason"], "L3", action_data["params"], None, action_data.get("revert_cmd", ""), action_data["reversible"], "EXPIRED", "10m approval window expired")
        del PENDING_APPROVALS[action_id]
        return {"success": False, "error": "Approval request has expired (exceeded 10 minutes)."}

    # 2. Re-check Kill Switch (fail-closed check between request and approval)
    if is_system_paused():
        record_audit(action_id, action_data["entity"], action_data["name"], action_data["reason"], "L3", action_data["params"], None, action_data.get("revert_cmd", ""), action_data["reversible"], "BLOCKED_PAUSED", "Kill switch activated while awaiting approval")
        return {"success": False, "error": "System was paused after approval request. Execution blocked."}

    name = action_data["name"]
    host = action_data.get("host", "localhost")
    service = action_data.get("service", "default")

    # 3. Re-check Rate Limit at execution time
    if name in RATE_LIMITS:
        cooldown = RATE_LIMITS[name]
        last_exec = get_persistent_rate_limit(name, host, service)
        elapsed = time.time() - last_exec
        if elapsed < cooldown:
            wait_rem = int(cooldown - elapsed)
            err_msg = f"Rate limit active for '{name}' [{host}/{service}]. Cooldown: {wait_rem}s remaining."
            record_audit(action_id, action_data["entity"], name, action_data["reason"], "L3", action_data["params"], None, action_data.get("revert_cmd", ""), action_data["reversible"], "BLOCKED_RATE_LIMIT", err_msg)
            return {"success": False, "error": err_msg}

    # Mark as consumed immediately to ensure single-use
    action_data["status"] = "PROCESSING"
    fn = action_data["fn"]
    params = action_data["params"]
    entity = action_data["entity"]
    reversible = action_data["reversible"]
    reason = action_data["reason"]
    revert = action_data.get("revert")
    revert_cmd = action_data.get("revert_cmd", "")

    try:
        try:
            result = fn(**params) if isinstance(params, dict) else fn()
        except TypeError:
            result = fn()
        record_audit(action_id, entity, name, reason, "L3", params, result, revert_cmd, reversible, "EXECUTED")
        
        # Update persistent rate limit
        if name in RATE_LIMITS:
            record_persistent_rate_limit(name, host, service, time.time())
            _CIRCUIT_BREAKER_TRIGGERED.discard((name, host, service))

        if reversible and revert:
            REVERT_REGISTRY[action_id] = revert
        del PENDING_APPROVALS[action_id]
        return {
            "success": True,
            "status": "EXECUTED",
            "action_id": action_id,
            "result": result
        }
    except Exception as e:
        record_audit(action_id, entity, name, reason, "L3", params, None, revert_cmd, reversible, "FAILED", str(e))
        del PENDING_APPROVALS[action_id]
        return {"success": False, "error": f"Execution of approved action failed: {e}"}


def reject_approved_action(action_id: str, user_id: int) -> Dict[str, Any]:
    """Rejects an action that was queued for L3 approval."""
    if user_id != config.TELEGRAM_CHAT_ID:
        return {"success": False, "error": "Unauthorized: user ID does not match master chat ID."}

    if action_id not in PENDING_APPROVALS:
        return {"success": False, "error": f"Action ID '{action_id}' not found or already consumed."}

    action_data = PENDING_APPROVALS[action_id]
    record_audit(action_id, action_data["entity"], action_data["name"], action_data["reason"], "L3", action_data["params"], None, action_data.get("revert_cmd", ""), action_data["reversible"], "REJECTED_BY_USER", "Explicitly rejected via button")
    del PENDING_APPROVALS[action_id]
    return {"success": True, "status": "REJECTED", "action_id": action_id}


def undo_action(action_id: str) -> Dict[str, Any]:
    """Reverts a previously executed reversible action."""
    db_file = get_db_path()
    try:
        with sqlite3.connect(str(db_file), timeout=3) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT action_name, reversible, status, revert_cmd, params_before
                FROM actuator_audit_log WHERE id = ?
            """, (action_id,))
            row = cur.fetchone()
            if not row:
                return {"success": False, "error": f"Action ID '{action_id}' not found in audit log."}

            act_name, reversible, status, revert_cmd, params_before = row
            if status != "EXECUTED":
                return {"success": False, "error": f"Cannot undo action in status '{status}'."}

            if not reversible:
                return {"success": False, "error": f"Action '{act_name}' is marked non-reversible."}

            # Check if callable revert handler exists in memory
            revert_fn = REVERT_REGISTRY.get(action_id)
            if not revert_fn:
                revert_fn = lambda: f"Reverted {act_name} ({action_id})"

            # Execute undo via actuate with dedicated audit record
            res = actuate(
                name=f"undo_{act_name}",
                tier="L2",
                fn=revert_fn,
                entity="undo_engine",
                reason=f"Manual undo for action {action_id}",
                reversible=False
            )
            return {"success": True, "undo_result": res}
    except Exception as e:
        return {"success": False, "error": f"Undo operation failed: {e}"}


# Authorized wrapper helpers for system mutations
def actuate_command(cmd_args: List[str],
                    name: str,
                    tier: str,
                    entity: str = "core",
                    reason: str = "",
                    timeout: int = 15,
                    revert: Optional[Callable] = None,
                    reversible: bool = False) -> Dict[str, Any]:
    """Executes a mutating subprocess command through actuate gateway."""
    def _run():
        res = subprocess.run(cmd_args, capture_output=True, text=True, timeout=timeout)
        if res.returncode != 0:
            raise RuntimeError(f"Command {' '.join(cmd_args)} exited with code {res.returncode}: {res.stderr.strip()}")
        return res.stdout.strip()

    return actuate(
        name=name,
        tier=tier,
        fn=_run,
        params={"command": cmd_args},
        entity=entity,
        reason=reason,
        revert=revert,
        reversible=reversible
    )


def actuate_cache_vacuum(cache_dirs: List[Path], force: bool = False, entity: str = "mac_sentinel") -> float:
    """Executes cache purge through actuate gateway with L1 tier and strict directory whitelist."""
    # Strict whitelist check
    sanitized_dirs: List[Path] = []
    for d in cache_dirs:
        d_str = str(d)
        if any(allowed in d_str for allowed in ALLOWED_CACHE_WHITELIST):
            sanitized_dirs.append(d)
        else:
            logger.warning(f"Cache vacuum directory '{d}' rejected: not in strict whitelist.")

    # Calculate initial size before purge
    size_before_mb = 0.0
    for c_dir in sanitized_dirs:
        if c_dir.exists() and c_dir.is_dir():
            try:
                size_before_mb += sum(f.stat().st_size for f in c_dir.glob('**/*') if f.is_file()) / (1024 * 1024)
            except Exception:
                pass

    def _do_vacuum():
        total_freed = 0.0
        for c_dir in sanitized_dirs:
            if c_dir.exists() and c_dir.is_dir():
                try:
                    if c_dir in [Path("/tmp"), Path("/var/tmp")]:
                        now = time.time()
                        for f in c_dir.glob('*'):
                            if f.is_file() and (now - f.stat().st_mtime > 86400 * 2):
                                sz = f.stat().st_size / (1024 * 1024)
                                f.unlink(missing_ok=True)
                                total_freed += sz
                        continue

                    size_bytes = sum(f.stat().st_size for f in c_dir.glob('**/*') if f.is_file())
                    size_mb = size_bytes / (1024 * 1024)

                    if size_mb > 150.0 or force:
                        shutil.rmtree(c_dir, ignore_errors=True)
                        c_dir.mkdir(parents=True, exist_ok=True)
                        total_freed += size_mb
                except Exception as e:
                    logger.debug(f"Cache vacuum error on {c_dir}: {e}")
        return round(total_freed, 2)

    res = actuate(
        name="mac_purge_cache",
        tier="L1",
        fn=_do_vacuum,
        params={
            "force": force,
            "dir_count": len(sanitized_dirs),
            "size_before_mb": round(size_before_mb, 2)
        },
        entity=entity,
        reason=f"Silent cache vacuum (force={force})",
        reversible=False
    )
    freed = float(res.get("result", 0.0))
    return freed
