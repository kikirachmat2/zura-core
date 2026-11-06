"""
ops/kibot_controller.py - Zura Autonomous KiBot V3 Controller & Tuning Engine
Direct Controller for KiBot V3 (70/30 Indodax DCA Trading Bot):
- Reads live SQLite DB (kibot_v3.db) on Server 1 (0ms latency)
- Ingests portfolio snapshots, position values, and DCA cycle history
- Autonomously tunes target allocation (e.g. 70/30 -> 80/20) and trade ceilings based on market regime
- Executes graceful service restart via systemctl when parameters are reconfigured
"""

import os
import sys
import shutil
import sqlite3
import logging
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.memory import log_decision, set_state
from core.actuator import actuate, ActuatorError, ActuatorApprovalRequired

logger = logging.getLogger("KiBotController")

CANDIDATE_KIBOT_PATHS = [
    Path("/home/ubuntu/KiBotV3/kibot_v3.db"),
    Path.home() / "Documents/Web Develop/KiBot/kibot_v3.db",
    BASE_DIR / "data/kibot_v3.db"
]

CANDIDATE_ENV_PATHS = [
    Path("/home/ubuntu/KiBotV3/.env"),
    Path.home() / "Documents/Web Develop/KiBot/.env"
]


class KiBotController:
    def __init__(self):
        self.db_path = self._find_database()
        self.env_path = self._find_env()

    def _find_database(self) -> Path:
        for p in CANDIDATE_KIBOT_PATHS:
            if p.exists():
                return p
        return CANDIDATE_KIBOT_PATHS[0]

    def _find_env(self) -> Optional[Path]:
        for p in CANDIDATE_ENV_PATHS:
            if p.exists():
                return p
        return None

    def is_connected(self) -> bool:
        return self.db_path.exists()

    def get_kibot_metrics(self) -> Dict[str, Any]:
        """Reads live portfolio state, last snapshot, and DCA parameters."""
        if not self.is_connected():
            return {
                "connected": False,
                "status": "DB_NOT_FOUND",
                "strategy": "70/30 Indodax DCA",
                "total_snapshots": 0
            }

        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 1. Total snapshots and latest snapshot
            cursor.execute("SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1")
            last_snap = cursor.fetchone()

            # 2. Total transactions
            cursor.execute("SELECT COUNT(*) as cnt FROM transactions")
            tx_cnt = cursor.fetchone()["cnt"]

            # 3. Last balance check state
            cursor.execute("SELECT * FROM system_state WHERE key = 'last_balance_snapshot'")
            state_row = cursor.fetchone()
            last_checked = state_row["updated_at"] if state_row else "N/A"

            conn.close()

            regime = last_snap["regime_phase"] if (last_snap and "regime_phase" in last_snap.keys()) else "ACCUMULATE_70_30"
            equity = last_snap["total_equity_idr"] if (last_snap and "total_equity_idr" in last_snap.keys()) else 0.0

            data = {
                "connected": True,
                "db_location": str(self.db_path),
                "strategy": "70% BTC / 30% ETH Indodax DCA",
                "regime": regime,
                "total_equity_idr": equity,
                "last_snapshot_time": last_snap["timestamp"] if last_snap else "N/A",
                "total_transactions": tx_cnt,
                "last_balance_check": last_checked,
                "timestamp": datetime.now().isoformat()
            }
            set_state("kibot_telemetry", data)

            # Auto-sync to Supabase shadow cloud
            try:
                self.sync_to_supabase()
            except Exception as se:
                logger.debug(f"Shadow sync to Supabase skipped: {se}")

            return data

        except Exception as e:
            logger.error(f"Error querying kibot_v3.db: {e}")
            return {"connected": False, "error": str(e)}

    def sync_to_supabase(self) -> Dict[str, Any]:
        """Synchronizes live KiBot SQLite data to Supabase Cloud."""
        try:
            from core.supabase_hub import sync_kibot_to_supabase
            return sync_kibot_to_supabase(self.db_path)
        except Exception as e:
            logger.warning(f"Failed to sync KiBot to Supabase: {e}")
            return {"success": False, "error": str(e)}

    def tune_market_regime(self, regime: str, btc_pct: float = 0.70, eth_pct: float = 0.30, max_trade_idr: Optional[float] = None) -> Dict[str, Any]:
        """
        Adjusts KiBot allocation and limits based on market condition via actuator gateway.
        Strict charter rule:
        - Locked to two numbers: 750,000 IDR and 1,500,000 IDR (Autonomous L2).
        - Outside these two numbers STRICTLY requires human approval (L3).
        - Rate limit: 1x/hour.
        - Backs up .env before write; params logged only as changed key.
        """
        target_val = max_trade_idr if max_trade_idr is not None else (1500000.0 if regime == "BULL" else 750000.0)
        logger.info(f"⚡ Tuning KiBot V3 parameters for market regime: {regime} (Target: {target_val} IDR)...")
        
        env_file = self.env_path
        if not env_file or not env_file.exists():
            return {"success": False, "reason": "KiBot .env not accessible"}

        # Guardrail: strict L3 approval if outside 750k / 1.5M
        is_locked_val = target_val in [750000.0, 1500000.0]
        tier = "L2" if is_locked_val else "L3"

        # Rotate up to 3 copies with chmod 600
        bak1 = env_file.with_name(f"{env_file.name}.bak.1")
        bak2 = env_file.with_name(f"{env_file.name}.bak.2")
        bak3 = env_file.with_name(f"{env_file.name}.bak.3")

        def _do_tune():
            # 1. Rotate backups (max 3 copies) and chmod 600
            try:
                if bak2.exists():
                    shutil.copyfile(bak2, bak3)
                    os.chmod(bak3, 0o600)
                if bak1.exists():
                    shutil.copyfile(bak1, bak2)
                    os.chmod(bak2, 0o600)
                shutil.copyfile(env_file, bak1)
                os.chmod(bak1, 0o600)
            except Exception as ex:
                logger.warning(f"Error rotating KiBot .env backups: {ex}")

            # 2. Modify only MAX_SINGLE_TRADE_IDR
            lines = env_file.read_text().splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("MAX_SINGLE_TRADE_IDR="):
                    new_lines.append(f"MAX_SINGLE_TRADE_IDR={target_val}")
                else:
                    new_lines.append(line)
            env_file.write_text("\n".join(new_lines) + "\n")
            os.chmod(env_file, 0o600)

            # 3. Trigger service restart via actuator (rate limited to 1x/hr)
            restart_output = "Skipped (not on server)"
            if sys.platform.startswith("linux"):
                def _do_restart():
                    rc = subprocess.run(["sudo", "/usr/bin/systemctl", "restart", "kibot-v3-core.service"], capture_output=True, text=True, timeout=10)
                    if rc.returncode != 0:
                        raise RuntimeError(f"KiBot restart failed: {rc.stderr.strip()}")
                    return "Restarted kibot-v3-core.service"

                restart_res = actuate(
                    name="kibot_restart_service",
                    tier="L2",
                    fn=_do_restart,
                    params={"service": "kibot-v3-core.service"},
                    entity="kibot_controller",
                    reason=f"Restart after tuning MAX_SINGLE_TRADE_IDR to {target_val}",
                    reversible=False
                )
                restart_output = str(restart_res.get("result", "Restarted"))

            log_decision(
                domain="KiBot Controller",
                trigger_event=f"Market regime evaluation: {regime}",
                decision_taken=f"Tuned MAX_SINGLE_TRADE_IDR to {target_val}",
                outcome=restart_output
            )
            return {
                "regime": regime,
                "btc_pct": btc_pct,
                "eth_pct": eth_pct,
                "target_val": target_val,
                "service_action": restart_output
            }

        def _revert_tune():
            if bak1.exists():
                shutil.copyfile(bak1, env_file)
                os.chmod(env_file, 0o600)
                if sys.platform.startswith("linux"):
                    subprocess.run(["sudo", "/usr/bin/systemctl", "restart", "kibot-v3-core.service"], capture_output=True, text=True, timeout=10)
                return "Restored KiBot .env from bak.1 and restarted service"
            return "No backup file found to restore"

        try:
            res = actuate(
                name="kibot_tune_env",
                tier=tier,
                fn=_do_tune,
                # ONLY log changed key and target value, NEVER full .env or secrets!
                params={"changed_key": "MAX_SINGLE_TRADE_IDR", "value": target_val, "regime": regime},
                entity="kibot_controller",
                reason=f"Market regime tune {regime} -> {target_val} IDR",
                revert=_revert_tune,
                reversible=True
            )
            return res
        except ActuatorError as ae:
            logger.warning(f"Actuator blocked KiBot tuning: {ae}")
            return {"success": False, "error": str(ae)}
        except Exception as e:
            logger.error(f"Failed to tune KiBot: {e}")
            return {"success": False, "error": str(e)}

    def emergency_stop(self, reason: str = "Circuit Breaker: Market anomaly or manual halt") -> Dict[str, Any]:
        """
        Instant Emergency Circuit Breaker:
        Stops kibot-v3-core.service immediately to prevent unintended trades during black-swan events.
        Reversible via Zura undo action.
        """
        def _do_stop():
            set_state("kibot_status", "EMERGENCY_HALTED")
            set_state("kibot_halt_timestamp", datetime.now().isoformat())
            if sys.platform.startswith("linux"):
                cmd = ["sudo", "/usr/bin/systemctl", "stop", "kibot-v3-core.service"]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if proc.returncode != 0:
                    raise RuntimeError(f"systemctl stop failed: {proc.stderr}")
                return "Stopped kibot-v3-core.service via systemctl"
            return "Simulated stop of kibot-v3-core.service on non-Linux"

        def _revert_stop():
            set_state("kibot_status", "ACTIVE")
            if sys.platform.startswith("linux"):
                cmd = ["sudo", "/usr/bin/systemctl", "start", "kibot-v3-core.service"]
                subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return "Restarted kibot-v3-core.service"

        try:
            return actuate(
                name="kibot_emergency_stop",
                tier="L2",
                fn=_do_stop,
                params={"action": "emergency_stop", "reason": reason, "host": "server1", "service": "kibot-v3-core.service"},
                entity="kibot_controller",
                reason=reason,
                revert=_revert_stop,
                reversible=True
            )
        except ActuatorError as ae:
            logger.warning(f"Actuator blocked emergency stop: {ae}")
            return {"success": False, "error": str(ae)}
        except Exception as e:
            logger.error(f"Failed to execute emergency stop: {e}")
            return {"success": False, "error": str(e)}


# Global instance
kibot_controller = KiBotController()
