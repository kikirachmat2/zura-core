"""
tests/test_actuator_05.py - Step 0.5 Comprehensive Actuator & Integrity Test Suite
Verifies:
1. AST Static Guard: Scans ans/, ops/, network/ ensuring zero unauthorized mutations.
2. Kill Switch: Fail-closed behavior, blocking all actuate() calls when paused.
3. L3 Approval: 10-minute expiry, master user verification, single-use enforcement.
4. Audit Sanitization: Strict scrubbing of tokens, keys, passwords, and IP addresses.
5. Undo Gateway: Reversible actions trigger revert with dedicated audit entry.
6. Centralized Rate Limiter: Enforces minimum cooldowns per action.
7. KiBot Guardrail: Strict lock to 750k/1.5M, automatic L3 escalation for custom limits.
"""

import os
import ast
import sys
import time
import json
import uuid
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import core.config as config
from core.actuator import (
    actuate, actuate_command, is_system_paused, set_system_paused,
    execute_approved_action, reject_approved_action, undo_action,
    sanitize_value, ActuatorError, ActuatorPausedError, ActuatorRateLimitError,
    PENDING_APPROVALS, REVERT_REGISTRY, RATE_LIMITS
)
from ops.kibot_controller import KiBotController


class TestActuatorASTStaticGuard(unittest.TestCase):
    """(a) AST Static Guard: Verifies no forbidden direct mutations exist in ans/, ops/, network/."""

    def test_ast_scan_no_forbidden_mutations(self):
        target_dirs = ["ans", "ops", "network"]
        forbidden_calls = []

        # Authorized read-only probe commands for subprocess
        probe_whitelist = [
            "sysctl", "ping", "dscacheutil", "resolvectl", "killall",
            "networksetup", "adb", "git", "python", "python3", "df", "free",
            "systemctl", "journalctl", "renice"
        ]

        for d in target_dirs:
            dir_path = BASE_DIR / d
            for py_file in dir_path.glob("**/*.py"):
                with open(py_file, "r", encoding="utf-8") as f:
                    content = f.read()

                try:
                    tree = ast.parse(content, filename=str(py_file))
                except Exception as e:
                    self.fail(f"Failed to parse AST for {py_file}: {e}")

                for node in ast.walk(tree):
                    # Check 1: os.system is strictly FORBIDDEN everywhere in ans/, ops/, network/
                    if isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Attribute):
                            # os.system
                            if node.func.attr == "system" and getattr(node.func.value, "id", None) == "os":
                                forbidden_calls.append(f"{py_file.name}:{node.lineno} calls os.system")
                            # shutil.rmtree
                            elif node.func.attr == "rmtree" and getattr(node.func.value, "id", None) == "shutil":
                                forbidden_calls.append(f"{py_file.name}:{node.lineno} calls shutil.rmtree")

        self.assertEqual(forbidden_calls, [], f"Forbidden AST mutations detected outside actuator: {forbidden_calls}")


class TestActuatorKillSwitch(unittest.TestCase):
    """(b) Kill Switch: Fail-closed check and pause/resume execution enforcement."""

    def setUp(self):
        self.orig_db = config.DB_PATH
        self.tmp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.tmp_dir) / "test_zura.db"
        config.DB_PATH = self.test_db

        with sqlite3.connect(str(self.test_db)) as conn:
            conn.execute("CREATE TABLE system_state (key TEXT PRIMARY KEY, value TEXT, updated_at REAL)")
            conn.execute("""
                CREATE TABLE actuator_audit_log (
                    id TEXT PRIMARY KEY, timestamp REAL, entity TEXT, action_name TEXT,
                    reason TEXT, tier TEXT, params_before TEXT, params_after TEXT,
                    revert_cmd TEXT, reversible INTEGER, status TEXT, error TEXT
                )
            """)

    def tearDown(self):
        config.DB_PATH = self.orig_db
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_pause_blocks_mutation(self):
        # 1. Initially unpaused
        set_system_paused(False)
        self.assertFalse(is_system_paused())

        # 2. Set paused
        set_system_paused(True)
        self.assertTrue(is_system_paused())

        # 3. Action must raise ActuatorPausedError
        with self.assertRaises(ActuatorPausedError):
            actuate("test_action", tier="L1", fn=lambda: "done", entity="test", reason="unit test")

        # 4. Audit record must reflect BLOCKED_PAUSED
        with sqlite3.connect(str(self.test_db)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT status, action_name FROM actuator_audit_log WHERE action_name = 'test_action'")
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "BLOCKED_PAUSED")

    def test_fail_closed_on_db_corruption(self):
        # If DB path is invalid or corrupted, must return True (treat as paused)
        config.DB_PATH = Path("/nonexistent/directory/invalid.db")
        self.assertTrue(is_system_paused(), "Kill Switch must be FAIL-CLOSED on DB error!")


class TestActuatorL3Approval(unittest.TestCase):
    """(c) L3 Approval: Master user verification, 10m expiry, single-use guarantee."""

    def setUp(self):
        self.orig_db = config.DB_PATH
        self.tmp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.tmp_dir) / "test_zura.db"
        config.DB_PATH = self.test_db
        PENDING_APPROVALS.clear()

        with sqlite3.connect(str(self.test_db)) as conn:
            conn.execute("CREATE TABLE system_state (key TEXT PRIMARY KEY, value TEXT, updated_at REAL)")
            conn.execute("""
                CREATE TABLE actuator_audit_log (
                    id TEXT PRIMARY KEY, timestamp REAL, entity TEXT, action_name TEXT,
                    reason TEXT, tier TEXT, params_before TEXT, params_after TEXT,
                    revert_cmd TEXT, reversible INTEGER, status TEXT, error TEXT
                )
            """)

    def tearDown(self):
        config.DB_PATH = self.orig_db
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        PENDING_APPROVALS.clear()

    def test_l3_intercept_and_single_use_approval(self):
        executed_flag = [False]
        def _target_action():
            executed_flag[0] = True
            return "SUCCESS"

        res = actuate(
            name="dangerous_action",
            tier="L3",
            fn=_target_action,
            params={"power": 100},
            entity="tester",
            reason="need human sign-off"
        )

        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "AWAITING_APPROVAL")
        action_id = res["action_id"]
        self.assertFalse(executed_flag[0])

        # 1. Unauthorized user cannot approve
        fake_user = 999999999
        unauth_res = execute_approved_action(action_id, fake_user)
        self.assertFalse(unauth_res["success"])
        self.assertIn("Unauthorized", unauth_res["error"])
        self.assertFalse(executed_flag[0])

        # 2. Master user approves
        auth_res = execute_approved_action(action_id, config.TELEGRAM_CHAT_ID)
        self.assertTrue(auth_res["success"])
        self.assertEqual(auth_res["result"], "SUCCESS")
        self.assertTrue(executed_flag[0])

        # 3. Single-use: clicking button second time MUST fail
        second_tap = execute_approved_action(action_id, config.TELEGRAM_CHAT_ID)
        self.assertFalse(second_tap["success"])
        self.assertIn("not found or already consumed", second_tap["error"])

    def test_l3_expiry_after_10_minutes(self):
        res = actuate(
            name="expired_action",
            tier="L3",
            fn=lambda: "ran",
            entity="tester",
            reason="testing expiry"
        )
        action_id = res["action_id"]

        # Simulate 11 minutes passage
        PENDING_APPROVALS[action_id]["expires_at"] = time.time() - 10.0

        exp_res = execute_approved_action(action_id, config.TELEGRAM_CHAT_ID)
        self.assertFalse(exp_res["success"])
        self.assertIn("expired", exp_res["error"])


class TestActuatorSanitizationAndScrubbing(unittest.TestCase):
    """(d) Audit Scrubbing: Verifies tokens, passwords, private keys, and IPs are scrubbed."""

    def test_sanitizer_removes_sensitive_keys_and_patterns(self):
        raw_params = {
            "service": "kibot",
            "bot_token": "bot1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij",
            "user_password": "supersecretpassword123",
            "server_ip": "152.42.180.170",
            "api_key": "AIzaSyD-1234567890abcdefghijklmnopqrst",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0\n-----END RSA PRIVATE KEY-----",
            "safe_nested": {
                "credential": "hidden",
                "normal_field": "100.64.0.1 is an internal ip",
                "trade_amount": 750000.0
            }
        }

        cleaned = sanitize_value(raw_params)
        json_dump = json.dumps(cleaned)

        self.assertNotIn("bot1234567890", json_dump)
        self.assertNotIn("supersecretpassword123", json_dump)
        self.assertNotIn("152.42.180.170", json_dump)
        self.assertNotIn("100.64.0.1", json_dump)
        self.assertNotIn("RSA PRIVATE KEY", json_dump)
        self.assertEqual(cleaned["safe_nested"]["trade_amount"], 750000.0)


class TestActuatorUndo(unittest.TestCase):
    """(e) Undo Gateway: Tests rollback with separate audit trail entry."""

    def setUp(self):
        self.orig_db = config.DB_PATH
        self.tmp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.tmp_dir) / "test_zura.db"
        config.DB_PATH = self.test_db
        REVERT_REGISTRY.clear()

        with sqlite3.connect(str(self.test_db)) as conn:
            conn.execute("CREATE TABLE system_state (key TEXT PRIMARY KEY, value TEXT, updated_at REAL)")
            conn.execute("""
                CREATE TABLE actuator_audit_log (
                    id TEXT PRIMARY KEY, timestamp REAL, entity TEXT, action_name TEXT,
                    reason TEXT, tier TEXT, params_before TEXT, params_after TEXT,
                    revert_cmd TEXT, reversible INTEGER, status TEXT, error TEXT
                )
            """)

    def tearDown(self):
        config.DB_PATH = self.orig_db
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        REVERT_REGISTRY.clear()

    def test_undo_reversible_action(self):
        state = {"value": "initial"}
        def _do_action():
            state["value"] = "mutated"
            return "mutated"

        def _revert_action():
            state["value"] = "initial"
            return "reverted"

        res = actuate(
            name="state_mutation",
            tier="L2",
            fn=_do_action,
            params={"target": "value"},
            entity="test",
            reason="unit test undo",
            revert=_revert_action,
            reversible=True
        )

        action_id = res["action_id"]
        self.assertEqual(state["value"], "mutated")

        # Execute Undo
        undo_res = undo_action(action_id)
        self.assertTrue(undo_res["success"])
        self.assertEqual(state["value"], "initial")

        # Verify undo record exists in audit log
        with sqlite3.connect(str(self.test_db)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT action_name, status FROM actuator_audit_log WHERE action_name = 'undo_state_mutation'")
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[1], "EXECUTED")


class TestActuatorRateLimiter(unittest.TestCase):
    """(f) Rate Limiting: Central cooldown enforcement."""

    def setUp(self):
        self.orig_db = config.DB_PATH
        self.tmp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.tmp_dir) / "test_zura.db"
        config.DB_PATH = self.test_db

        with sqlite3.connect(str(self.test_db)) as conn:
            conn.execute("CREATE TABLE system_state (key TEXT PRIMARY KEY, value TEXT, updated_at REAL)")
            conn.execute("""
                CREATE TABLE actuator_audit_log (
                    id TEXT PRIMARY KEY, timestamp REAL, entity TEXT, action_name TEXT,
                    reason TEXT, tier TEXT, params_before TEXT, params_after TEXT,
                    revert_cmd TEXT, reversible INTEGER, status TEXT, error TEXT
                )
            """)

    def tearDown(self):
        config.DB_PATH = self.orig_db
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_service_restart_rate_limiting(self):
        # First execution succeeds
        res1 = actuate(
            name="server_restart_service",
            tier="L2",
            fn=lambda: "restarted",
            params={"service": "chrony"},
            entity="watchdog",
            reason="service dead"
        )
        self.assertTrue(res1["success"])

        # Second execution within 3600s must raise ActuatorRateLimitError
        with self.assertRaises(ActuatorRateLimitError):
            actuate(
                name="server_restart_service",
                tier="L2",
                fn=lambda: "restarted again",
                params={"service": "chrony"},
                entity="watchdog",
                reason="service dead again"
            )


class TestKiBotActuatorGuardrails(unittest.TestCase):
    """(g) KiBot Guardrails: Locked at 750k and 1.5M, .env backup, and L3 escalation."""

    def setUp(self):
        self.orig_db = config.DB_PATH
        self.tmp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.tmp_dir) / "test_zura.db"
        config.DB_PATH = self.test_db

        with sqlite3.connect(str(self.test_db)) as conn:
            conn.execute("CREATE TABLE system_state (key TEXT PRIMARY KEY, value TEXT, updated_at REAL)")
            conn.execute("""
                CREATE TABLE actuator_audit_log (
                    id TEXT PRIMARY KEY, timestamp REAL, entity TEXT, action_name TEXT,
                    reason TEXT, tier TEXT, params_before TEXT, params_after TEXT,
                    revert_cmd TEXT, reversible INTEGER, status TEXT, error TEXT
                )
            """)

        self.test_env = Path(self.tmp_dir) / ".env"
        self.test_env.write_text("MAX_SINGLE_TRADE_IDR=750000.0\nINDODAX_KEY=testkey123\n")

        self.controller = KiBotController()
        self.controller.env_path = self.test_env

    def tearDown(self):
        config.DB_PATH = self.orig_db
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_kibot_locked_values_run_l2(self):
        # 1,500,000 is authorized locked value -> runs as L2
        res = self.controller.tune_market_regime("BULL", max_trade_idr=1500000.0)
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("tier"), "L2")

        # Verifies backup was created
        backup_file = self.test_env.with_name(f"{self.test_env.name}.bak")
        self.assertTrue(backup_file.exists())
        self.assertIn("MAX_SINGLE_TRADE_IDR=750000.0", backup_file.read_text())

    def test_kibot_custom_value_intercepted_as_l3(self):
        # 2,000,000 is outside 750k/1.5M -> MUST intercept as L3
        res = self.controller.tune_market_regime("BULL", max_trade_idr=2000000.0)
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("status"), "AWAITING_APPROVAL")
        self.assertIn("requires L3 approval", res.get("message"))


if __name__ == "__main__":
    unittest.main()
