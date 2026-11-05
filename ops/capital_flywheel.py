"""
ops/capital_flywheel.py - Zura Unified Capital & Wealth Flywheel
Connects Threads Shopee Affiliate Cashflow with KiBot Crypto DCA:
1. Reads realized paid commissions from kisahkomisi.db.
2. Tracks unallocated profits vs reallocated investments in financial_ledger.
3. During Extreme Fear or market dips, recommends/triggers capital injection
   from affiliate cashflow to Indodax IDR to absorb BTC/ETH at discount.
4. Synthesizes a holistic ROI & wealth growth flywheel metric for Bos Kiki.
"""

import sqlite3
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional

from core.memory import get_connection, log_decision, set_state, get_state
from ops.kibot_reconciler import kibot_reconciler

logger = logging.getLogger("CapitalFlywheel")

CANDIDATE_THREADS_DBS = [
    Path("/home/ubuntu/kisahkomisi-bot/data/kisahkomisi.db"),
    Path.home() / "Documents/Web Develop/Kisah Komisi/kisahkomisi-bot/data/kisahkomisi.db",
    Path(__file__).resolve().parent.parent / "data/kisahkomisi.db"
]


class CapitalFlywheel:
    MIN_INJECTION_IDR = 100_000.0  # Minimum Indodax transaction threshold

    def __init__(self, threads_db: Optional[Path] = None):
        self.threads_db = threads_db if threads_db else self._find_threads_db()

    def _find_threads_db(self) -> Path:
        for p in CANDIDATE_THREADS_DBS:
            if p.exists():
                return p
        return CANDIDATE_THREADS_DBS[0]

    def get_realized_shopee_commissions(self) -> float:
        """Extracts total paid commission from kisahkomisi.db."""
        if not self.threads_db.exists():
            return 0.0

        try:
            with sqlite3.connect(str(self.threads_db), timeout=4) as conn:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='commissions'")
                if not cur.fetchone():
                    return 0.0

                cur.execute("SELECT SUM(amount) FROM commissions WHERE status = 'paid'")
                row = cur.fetchone()
                return float(row[0] or 0.0)
        except Exception as e:
            logger.warning(f"Could not read Shopee commissions from DB: {e}")
            return 0.0

    def get_reallocated_capital(self) -> float:
        """Calculates total affiliate profit already reallocated to investments."""
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT SUM(amount) FROM financial_ledger 
                    WHERE flow_type = 'expense' AND category = 'capital_flywheel_dca'
                """)
                row = cur.fetchone()
                return float(row[0] or 0.0)
        except Exception as e:
            logger.warning(f"Could not read reallocated capital: {e}")
            return 0.0

    def evaluate_flywheel_cycle(self) -> Dict[str, Any]:
        """
        Evaluates the capital rotation opportunity between Threads and KiBot:
        - Calculates available unallocated commissions
        - Reads live market sentiment (Fear & Greed Index)
        - Advises capital rotation to DCA when market is discounted
        """
        total_commissions = self.get_realized_shopee_commissions()
        total_reallocated = self.get_reallocated_capital()
        available_pool = max(0.0, total_commissions - total_reallocated)

        sentiment = kibot_reconciler.get_market_sentiment()
        fng_val = sentiment.get("value", 50)
        is_discount_zone = fng_val <= 45

        can_inject = available_pool >= self.MIN_INJECTION_IDR
        recommended_action = "HOLD_CASH"
        advice = "Komisi Shopee aman, belum mencapai ambang rotasi modal."

        if can_inject:
            if fng_val < 25:
                recommended_action = "AGGRESSIVE_INJECT_DCA"
                advice = (
                    f"Pasar Extreme Fear (F&G: {fng_val})! Putar Rp {available_pool:,.0f} dari komisi Shopee "
                    f"ke Indodax untuk menyerap BTC/ETH di harga diskon besar."
                )
            elif fng_val <= 45:
                recommended_action = "MODERATE_INJECT_DCA"
                advice = (
                    f"Pasar Mild Fear (F&G: {fng_val}). Rotasi Rp {available_pool:,.0f} komisi Shopee "
                    f"sebagai modal DCA tambahan."
                )
            else:
                recommended_action = "ACCUMULATE_CASH_BUFFER"
                advice = (
                    f"Pasar Netral/Greed (F&G: {fng_val}). Tahan komisi Rp {available_pool:,.0f} "
                    f"sebagai cadangan kas likuid (dry powder)."
                )

        cycle_state = {
            "timestamp": time.time(),
            "total_shopee_commissions_idr": total_commissions,
            "total_reallocated_idr": total_reallocated,
            "available_pool_idr": available_pool,
            "market_fng": fng_val,
            "is_discount_zone": is_discount_zone,
            "recommended_action": recommended_action,
            "advice": advice
        }

        set_state("capital_flywheel_state", cycle_state)
        return cycle_state

    def record_capital_reallocation(self, amount: float, description: str = "Rotasi komisi Shopee ke DCA KiBot") -> bool:
        """Records an actual or approved rotation of affiliate profits to Indodax DCA."""
        if amount <= 0:
            return False

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                import datetime
                today_str = datetime.date.today().isoformat()
                cur.execute("""
                    INSERT INTO financial_ledger (date, amount, flow_type, category, description, source, timestamp)
                    VALUES (?, ?, 'expense', 'capital_flywheel_dca', ?, 'shopee_affiliate', ?)
                """, (today_str, amount, description, time.time()))
                conn.commit()

            log_decision(
                domain="capital_flywheel",
                trigger_event="Capital rotation executed",
                decision_taken=f"Reallocated Rp {amount:,.0f} from Shopee commissions to KiBot DCA",
                outcome="SUCCESS"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to record capital reallocation: {e}")
            return False


# Global instance
capital_flywheel = CapitalFlywheel()

