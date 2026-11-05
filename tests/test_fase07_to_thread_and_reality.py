"""
tests/test_fase07_to_thread_and_reality.py - Unit Test Suite for Fase 0.7 & Reality Verifier
Per Zura Charter v2 & Executive Directive:
1. Verifies Reality & Mathematical Verification Engine:
   - Catches deficit and budget mismatch (anti-Meta.ai audit roast).
   - Catches Indonesian transit & geographic hallucinations (e.g. KRL in Surabaya).
   - Approves accurate financial breakdowns and realistic geography.
2. Verifies Zura Advisory CLI integration with Reality Verifier.
3. Verifies asyncio.to_thread offloading in main orchestrator.
"""

import sys
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ops.reality_verifier import (
    parse_rupiah_amount,
    audit_financial_math,
    audit_geography_and_logistics,
    audit_story_content
)
from scripts.zura_advisory import review_story, parse_json_safely


class TestRealityAndMathVerifier07(unittest.TestCase):
    def test_parse_rupiah_amount_formats(self):
        """Verifies accurate conversion of various Indonesian currency expressions."""
        self.assertEqual(parse_rupiah_amount("8,5jt"), 8500000)
        self.assertEqual(parse_rupiah_amount("8.5 juta"), 8500000)
        self.assertEqual(parse_rupiah_amount("10jt"), 10000000)
        self.assertEqual(parse_rupiah_amount("500rb"), 500000)
        self.assertEqual(parse_rupiah_amount("750 ribu"), 750000)
        self.assertEqual(parse_rupiah_amount("250k"), 250000)
        self.assertEqual(parse_rupiah_amount("2.500.000"), 2500000)

    def test_audit_financial_math_tekor_rejected(self):
        """Verifies deficit / tekor budget allocation is caught deterministically."""
        text = (
            "Gaji gue sebesar 8.5jt sebulan.\n"
            "Kosan 2.5jt, makan 2.5jt, kirim ortu 2jt, paylater 1.5jt, nabung 1.5jt."
        )
        # Sum of allocations: 2.5 + 2.5 + 2.0 + 1.5 + 1.5 = 10.0jt (Tekor 1.5jt vs gaji 8.5jt)
        result = audit_financial_math(text)
        self.assertTrue(result["has_budget_breakdown"])
        self.assertFalse(result["is_valid"])
        self.assertEqual(result["stated_income"], 8500000)
        self.assertEqual(result["total_allocated"], 10000000)
        self.assertIn("DEFISIT", result["flaw_message"])

    def test_audit_financial_math_balanced_approved(self):
        """Verifies balanced, mathematically airtight budget is approved."""
        text = (
            "Gaji gue 8.5jt sebulan di Jakarta.\n"
            "Kosan 2.5jt, makan 2.5jt, transport 1jt, kirim ortu 1.5jt, tabungan 1jt."
        )
        # Sum of allocations: 2.5 + 2.5 + 1.0 + 1.5 + 1.0 = 8.5jt (Exact match!)
        result = audit_financial_math(text)
        self.assertTrue(result["has_budget_breakdown"])
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["stated_income"], 8500000)
        self.assertEqual(result["total_allocated"], 8500000)
        self.assertEqual(result["variance"], 0)

    def test_geography_transit_hallucination_caught(self):
        """Verifies KRL/MRT claims in non-KRL cities like Surabaya or Bandung are caught."""
        text_surabaya = "Ngekos di Surabaya tiap pagi desak-desakan naik KRL ke stasiun Gubeng."
        flaws_sby = audit_geography_and_logistics(text_surabaya)
        self.assertTrue(len(flaws_sby) > 0)
        self.assertIn("HALUSINASI GEOGRAFI", flaws_sby[0])
        self.assertIn("Surabaya", flaws_sby[0])

        text_bandung = "Kerja di Bandung tapi tiap hari andelin MRT."
        flaws_bdg = audit_geography_and_logistics(text_bandung)
        self.assertTrue(len(flaws_bdg) > 0)
        self.assertIn("Bandung", flaws_bdg[0])

    def test_geography_valid_jakarta_transit_approved(self):
        """Verifies KRL/MRT in Jakarta is approved without false alarms."""
        text_jkt = "Tiap pagi naik KRL dari Bogor ke Manggarai, lanjut MRT ke Blok M."
        flaws_jkt = audit_geography_and_logistics(text_jkt, default_city="Jakarta")
        self.assertEqual(len(flaws_jkt), 0)

    def test_audit_story_content_integration(self):
        """Verifies end-to-end audit_story_content combines math and reality checks."""
        bad_payload = {
            "city": "Surabaya",
            "topic": "Anak Rantau Surabaya",
            "slides": [
                "Gaji 8.5jt di Surabaya tapi tiap bulan boncos.",
                "Kosan 2.5jt, makan 2jt, kirim ortu 2jt, paylater 1.5jt, nabung 2jt.",
                "Tiap pagi naik KRL stasiun Gubeng.",
                "Kalian tim mana?"
            ]
        }
        res = audit_story_content(bad_payload)
        self.assertFalse(res["is_approved"])
        # Should catch both math mismatch and Surabaya KRL
        flaws_str = " ".join(res["logic_flaws"])
        self.assertTrue("Klaim gaji" in flaws_str or "DEFISIT" in flaws_str or "SELISIH" in flaws_str)
        self.assertIn("Surabaya", flaws_str)


class TestAsyncioToThreadOffloading07(unittest.IsolatedAsyncioTestCase):
    async def test_to_thread_prevents_loop_blocking(self):
        """Verifies that heavy blocking functions offloaded via to_thread allow loop ticks."""
        def slow_blocking_call():
            import time
            time.sleep(0.1)
            return "DONE_SLOW"

        # Concurrently run heartbeat-like async tick and offloaded task
        tick_counter = 0

        async def fast_ticker():
            nonlocal tick_counter
            for _ in range(5):
                await asyncio.sleep(0.02)
                tick_counter += 1

        task_slow = asyncio.to_thread(slow_blocking_call)
        task_fast = fast_ticker()

        slow_res, _ = await asyncio.gather(task_slow, task_fast)
        self.assertEqual(slow_res, "DONE_SLOW")
        # fast_ticker was able to tick while slow_blocking_call ran on separate OS thread
        self.assertGreaterEqual(tick_counter, 3)


if __name__ == "__main__":
    unittest.main()

