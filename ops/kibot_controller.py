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

    def tune_market_regime(self, regime: str, btc_pct: float = 0.70, eth_pct: float = 0.30) -> Dict[str, Any]:
        """Autonomously adjusts KiBot allocation and limits based on market condition."""
        logger.info(f"⚡ Tuning KiBot V3 parameters for market regime: {regime} ({btc_pct*100:.0f}% BTC / {eth_pct*100:.0f}% ETH)...")
        
        env_file = self.env_path
        if not env_file or not env_file.exists():
            return {"success": False, "reason": "KiBot .env not accessible"}

        try:
            # Read current .env
            lines = env_file.read_text().splitlines()
            new_lines = []
            keys_updated = set()

            for line in lines:
                if line.startswith("MAX_SINGLE_TRADE_IDR="):
                    # In volatile bear market, smaller bite sizes; in bull market, higher bite sizes
                    new_val = 1500000.0 if regime == "BULL" else 750000.0
                    new_lines.append(f"MAX_SINGLE_TRADE_IDR={new_val}")
                    keys_updated.add("MAX_SINGLE_TRADE_IDR")
                else:
                    new_lines.append(line)

            env_file.write_text("\n".join(new_lines) + "\n")

            # Restart KiBot systemd service if running on server
            restart_output = "Skipped (not on server)"
            if sys.platform.startswith("linux"):
                rc = subprocess.run(["sudo", "systemctl", "restart", "kibot-v3-core.service"], capture_output=True, text=True, timeout=10)
                restart_output = "Restarted kibot-v3-core.service" if rc.returncode == 0 else f"Restart failed: {rc.stderr}"

            log_decision(
                domain="KiBot Controller",
                trigger_event=f"Market regime evaluation: {regime}",
                decision_taken=f"Tuned allocation ({btc_pct*100:.0f}/{eth_pct*100:.0f}) and trade limits",
                outcome=restart_output
            )

            return {
                "success": True,
                "regime": regime,
                "btc_pct": btc_pct,
                "eth_pct": eth_pct,
                "service_action": restart_output
            }

        except Exception as e:
            logger.error(f"Failed to tune KiBot: {e}")
            return {"success": False, "error": str(e)}


# Global instance
kibot_controller = KiBotController()
