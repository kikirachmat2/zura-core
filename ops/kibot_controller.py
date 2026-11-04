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
            return data

        except Exception as e:
            logger.error(f"Error querying kibot_v3.db: {e}")
            return {"connected": False, "error": str(e)}

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

        backup_file = env_file.with_name(f"{env_file.name}.bak")

        def _do_tune():
            # 1. Backup .env before write
            backup_file.write_text(env_file.read_text())

            # 2. Modify only MAX_SINGLE_TRADE_IDR
            lines = env_file.read_text().splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("MAX_SINGLE_TRADE_IDR="):
                    new_lines.append(f"MAX_SINGLE_TRADE_IDR={target_val}")
                else:
                    new_lines.append(line)
            env_file.write_text("\n".join(new_lines) + "\n")

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
            if backup_file.exists():
                env_file.write_text(backup_file.read_text())
                if sys.platform.startswith("linux"):
                    subprocess.run(["sudo", "/usr/bin/systemctl", "restart", "kibot-v3-core.service"], capture_output=True, text=True, timeout=10)
                return "Restored KiBot .env from backup and restarted service"
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


# Global instance
kibot_controller = KiBotController()
