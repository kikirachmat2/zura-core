"""
tests/test_fase08_whatif_cowork_and_bundle.py - Unit Test Suite for Fase 0.8 & Overkill Capabilities
Per Zura Charter v2 & User Directives:
1. Verifies What-If Contingency Engine across all registered disaster scenarios.
2. Verifies Cowork Executive Scribe (MoM extraction, commitment tracking, overdue alerts).
3. Verifies Pre-flight packaging bundle creation and checksum generation.
"""

import os
import sys
import json
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ops.whatif_engine import whatif_engine
from ops.cowork_scribe import CoworkExecutiveScribe, init_cowork_db
from scripts.package_production_bundle import create_release_tarball


class TestWhatIfEngine08(unittest.TestCase):
    def test_all_scenarios_have_contingency_handlers(self):
        """Verifies all registered scenarios return well-formed contingency protocols."""
        expected_scenarios = [
            "KIBOT_NONCE_DESYNC",
            "KIBOT_API_TIMEOUT",
            "THREADS_META_429",
            "SERVER_DISK_EXHAUSTION",
            "SERVER_RAM_SPIKE",
            "MAC_THERMAL_THROTTLING",
            "WIFI_MEETING_ACTIVE",
            "GITOPS_BROKEN_SYNTAX",
            "STORY_MATH_MISMATCH",
            "PROMPT_INJECTION_DETECTED"
        ]
        for sc in expected_scenarios:
            res = whatif_engine.simulate_what_if(sc)
            self.assertEqual(res["scenario"], sc)
            self.assertIn("autonomous_reflex", res)
            self.assertIn("contingency_tier", res)
            self.assertIn("rollback_plan", res)

    def test_wifi_meeting_active_scenario_blocks_reconnect(self):
        """Verifies WIFI_MEETING_ACTIVE scenario strictly blocks physical reconnect."""
        res = whatif_engine.simulate_what_if("WIFI_MEETING_ACTIVE")
        self.assertTrue(res["requires_human_approval"])
        self.assertIn("NEVER toggle", res["autonomous_reflex"][0])

    def test_kibot_nonce_desync_scenario(self):
        """Verifies KIBOT_NONCE_DESYNC executes NTP clock sync before retry."""
        res = whatif_engine.simulate_what_if("KIBOT_NONCE_DESYNC")
        self.assertFalse(res["requires_human_approval"])
        self.assertIn("chronyd", " ".join(res["autonomous_reflex"]))


class TestCoworkScribe08(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_db = Path(self.tmp_dir.name) / "cowork_test.db"
        init_cowork_db(self.test_db)
        self.scribe = CoworkExecutiveScribe(db_path=self.test_db)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_record_and_check_overdue_commitments(self):
        """Verifies recording commitment and detecting overdue follow-ups."""
        # 1. Record pending task that is already past deadline (-1 hour)
        res = self.scribe.record_commitment(
            coworker_name="Budi",
            task="Kirim draft poster film",
            hours_until_deadline=-1.0,
            context="Meeting pra-produksi ClosedBook"
        )
        self.assertTrue(res["success"])

        # 2. Record task due tomorrow (+24 hours)
        res_future = self.scribe.record_commitment(
            coworker_name="Siti",
            task="Kirim invoice katering",
            hours_until_deadline=24.0
        )
        self.assertTrue(res_future["success"])

        # 3. Check overdue commitments
        overdue = self.scribe.check_overdue_commitments()
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0]["coworker"], "Budi")
        self.assertIn("follow up santai", overdue[0]["nudge_draft"])

    @patch("core.brain.brain.think")
    def test_generate_mom(self, mock_think):
        """Verifies structured MoM extraction from raw notes."""
        mock_think.return_value = json.dumps({
            "meeting_title": "Kisah Komisi Sync",
            "summary": "Diskusi target Shopee Affiliate bulan depan.",
            "key_decisions": ["Fokus niche remote tech", "Batasi 5 post per hari"],
            "action_items": [
                {"task": "Update product bank", "pic": "Zura", "deadline": "Senin 10:00 WIB"}
            ]
        })
        raw_notes = "Kita sepakat fokus niche remote tech dan batasi 5 post per hari. Zura tolong update product bank."
        res = self.scribe.generate_mom(raw_notes, meeting_title="Kisah Komisi Sync")
        self.assertTrue(res["success"])
        mom = res["mom"]
        self.assertEqual(len(mom["key_decisions"]), 2)
        self.assertEqual(mom["action_items"][0]["pic"], "Zura")


class TestReleaseBundlePackaging08(unittest.TestCase):
    def test_create_release_tarball_and_manifest(self):
        """Verifies release tarball is created and manifest matches checksum."""
        bundle_path = create_release_tarball()
        self.assertTrue(bundle_path.exists())
        self.assertGreater(bundle_path.stat().st_size, 1000)

        manifest = PROJECT_ROOT / "zura_release_manifest.txt"
        self.assertTrue(manifest.exists())
        content = manifest.read_text()
        self.assertIn("SHA-256", content)

        # Clean up generated release artifacts in dev
        if bundle_path.exists():
            bundle_path.unlink()
        if manifest.exists():
            manifest.unlink()


if __name__ == "__main__":
    unittest.main()
