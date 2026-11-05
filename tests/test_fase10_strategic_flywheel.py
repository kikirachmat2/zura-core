"""
tests/test_fase10_strategic_flywheel.py - Comprehensive Unit Tests for Phase 10
Tests:
1. Capital Flywheel: evaluating commission rotation to Indodax DCA based on Fear & Greed.
2. Mobile Sentinel: Field Work Mode dynamically overriding battery ceiling from 80% to 100%.
3. Threads Governor: Empirical Warganet Alignment Score (word cadence, lowercase ratio, ending tension).
4. KiBot Reconciler: Dynamic Profit-Taking and Cycle Rebalancing at Extreme Greed (>80).
5. Long-term User Profile & Preferences memory persistence.
"""

import unittest
import time
from unittest.mock import patch, MagicMock
from pathlib import Path

from ops.capital_flywheel import CapitalFlywheel
from ans.mobile_sentinel import MobileSentinel
from ops.threads_governor import ThreadsGovernor
from ops.kibot_reconciler import IndodaxReconciler
from core.memory import set_user_preference, get_all_user_preferences, get_state, set_state


class TestStrategicFlywheelAndHardening(unittest.TestCase):

    def test_01_capital_flywheel_evaluation(self):
        flywheel = CapitalFlywheel(threads_db=Path("/tmp/non_existent_db.db"))
        
        # Mock realized commissions and market sentiment (Extreme Fear)
        with patch.object(flywheel, "get_realized_shopee_commissions", return_value=350000.0), \
             patch.object(flywheel, "get_reallocated_capital", return_value=50000.0), \
             patch("ops.capital_flywheel.kibot_reconciler.get_market_sentiment", return_value={"value": 20}):
            
            res = flywheel.evaluate_flywheel_cycle()
            self.assertEqual(res["available_pool_idr"], 300000.0)
            self.assertEqual(res["market_fng"], 20)
            self.assertTrue(res["is_discount_zone"])
            self.assertEqual(res["recommended_action"], "AGGRESSIVE_INJECT_DCA")
            self.assertIn("Extreme Fear", res["advice"])

    def test_02_capital_flywheel_reallocation_record(self):
        flywheel = CapitalFlywheel()
        success = flywheel.record_capital_reallocation(150000.0, "Test injection to Indodax DCA")
        self.assertTrue(success)

    def test_03_mobile_field_work_mode_toggle(self):
        sentinel = MobileSentinel()
        
        # 1. Enable Field Work Mode for 8 hours -> Ceiling raises to 100%
        res = sentinel.set_field_work_mode(enabled=True, duration_hours=8.0)
        self.assertTrue(res["active"])
        self.assertEqual(res["charge_ceiling"], 100)
        
        # Verify in state
        field_state = get_state("mobile_field_mode")
        self.assertTrue(field_state["active"])
        self.assertGreater(field_state["expires_at"], time.time())

        # 2. Disable Field Work Mode -> Ceiling restores to 80%
        res_off = sentinel.set_field_work_mode(enabled=False)
        self.assertFalse(res_off["active"])
        self.assertEqual(res_off["charge_ceiling"], 80)

    def test_04_threads_empirical_alignment_score(self):
        gov = ThreadsGovernor()

        # High quality human-like slides (lowercase, 20 words each, dilemma ending)
        good_slides = [
            "gaji 6 juta di jakarta mepet bgt rasanya, apalagi kosan udah 1.8jt sendiri di jakpus.",
            "belum lagi kirim ortu sejuta sama transport krl ojol tiap hari kerja di agency.",
            "sisa sejuta buat tabungan darurat, terus ada temen ngajak nongki abis 500rb semalem.",
            "mending jujur nolak demi cashflow, atau ikut nongki biar gak dibilang sombong? spill strategi lu."
        ]
        res_good = gov.calculate_empirical_alignment_score(good_slides, topic="Gaji UMR")
        self.assertTrue(res_good["passed"])
        self.assertGreaterEqual(res_good["score"], 80.0)

        # Poor quality robot-like slides (all uppercase, 70 words, no ending dilemma)
        bad_slides = [
            "MENILIK SITUASI EKONOMI MAKRO SAAT INI YANG MANA PENGELUARAN MASYARAKAT KOTA METROPOLITAN SEMAKIN MENINGKAT SECARA SIGNIFIKAN DI BERBAGAI SEKTOR RIIL BAIK PRIMER MAUPUN SEKUNDER SEHINGGA MEMBUAT MASYARAKAT MENGALAMI DEFISIT KAS BULANAN YANG BERKELANJUTAN TANPA ADANYA INTERVENSI DARI LEMBAGA KEUANGAN TERKAIT KENDATI DEMIKIAN PERLU DICATAT BAHWA DIVERSIFIKASI PENDAPATAN MERUPAKAN SOLUSI MUTLAK.",
            "SEKIAN INFORMASI HARI INI."
        ]
        res_bad = gov.calculate_empirical_alignment_score(bad_slides, topic="Formal News")
        self.assertFalse(res_bad["passed"])
        self.assertLess(res_bad["score"], 70.0)

    def test_05_kibot_cycle_profit_taking_rebalancing(self):
        reconciler = IndodaxReconciler()

        # Test Extreme Greed (F&G = 88) -> Should trigger TAKE_PROFIT_REBALANCE
        plan_peak = reconciler.evaluate_cycle_rebalancing(fng_value=88, snapshot={})
        self.assertEqual(plan_peak["action"], "TAKE_PROFIT_REBALANCE")
        self.assertEqual(plan_peak["target_take_profit_pct"], 15.0)
        self.assertEqual(plan_peak["urgency"], "HIGH")
        self.assertIn("Extreme Greed", plan_peak["advice"])

        # Test Normal Market (F&G = 48) -> Should maintain portfolio
        plan_normal = reconciler.evaluate_cycle_rebalancing(fng_value=48, snapshot={})
        self.assertEqual(plan_normal["action"], "MAINTAIN_PORTFOLIO")
        self.assertEqual(plan_normal["target_take_profit_pct"], 0.0)

    def test_06_long_term_user_profile_memory(self):
        set_user_preference("identity", "preferred_editor", "VSCode + Antigravity", confidence=1.0)
        prefs = get_all_user_preferences()
        self.assertIn("preferred_editor", prefs)
        self.assertEqual(prefs["preferred_editor"], "VSCode + Antigravity")


if __name__ == "__main__":
    unittest.main()

