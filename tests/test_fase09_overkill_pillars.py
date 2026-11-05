"""
tests/test_fase09_overkill_pillars.py - Complete Unit & Integration Suite for Zura Overkill Upgrades
Verifies:
1. ShopeeCurator: Link validation, stockout detection, replacement curation, tracking URL formatting.
2. IndodaxReconciler: Public ticker calculation, Fear & Greed sentiment mapping, audit structure.
3. KiBotController: Emergency circuit breaker (stop & revert) and actuator rate-limits.
4. MobileSentinel: POCO M3 telemetry parsing, thermal alarm (>40°C), and 80% overcharge warnings.
5. ZuraBrain Memory Protection: Dynamic skip of heavy local Ollama when RAM is constrained (<1.5GB).
6. WhatIfEngine: 6 new disaster contingency handlers.
7. ServerWatchdog: OCI anti-reclaim micro-pulse.
"""

import os
import sys
import unittest
import tempfile
import sqlite3
from unittest.mock import patch, MagicMock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.actuator import (
    set_actuator_db_path,
    init_actuator_db,
    record_persistent_rate_limit,
    ActuatorRateLimitError,
    actuate,
    undo_action
)
from ops.shopee_curator import ShopeeCurator
from ops.kibot_reconciler import IndodaxReconciler
from ops.kibot_controller import KiBotController
from ans.mobile_sentinel import MobileSentinel
from ans.server_watchdog import ServerWatchdog
from ops.whatif_engine import whatif_engine
from core.brain import ZuraBrain


class TestShopeeCurator(unittest.TestCase):
    def setUp(self):
        self.curator = ShopeeCurator()

    @patch("requests.get")
    def test_validate_link_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.url = "https://shopee.co.id/product/123/456"
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = ["<html><body>Beli Sekarang Ready Stok</body></html>"]
        mock_get.return_value = mock_resp

        res = self.curator.validate_link("https://s.shopee.co.id/testlink")
        self.assertTrue(res["valid"])
        self.assertEqual(res["status_code"], 200)

    @patch("requests.get")
    def test_validate_link_detects_out_of_stock(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.url = "https://shopee.co.id/product/123/456"
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = ["<html><body>Maaf, produk tidak ditemukan atau habis terjual</body></html>"]
        mock_get.return_value = mock_resp

        res = self.curator.validate_link("https://s.shopee.co.id/soldout")
        self.assertFalse(res["valid"])
        self.assertIn("out of stock", res["reason"].lower())

    def test_curate_replacement_evergreen(self):
        rep = self.curator.curate_replacement(niche="financial")
        self.assertIsNotNone(rep)
        self.assertIn("product_name", rep)
        self.assertIn("product_url", rep)
        self.assertTrue(rep["product_url"].startswith("http"))

    def test_format_affiliate_link(self):
        url = "https://s.shopee.co.id/sample123"
        formatted = self.curator.format_affiliate_link(url, sub_id="kikipunyacerita")
        self.assertIn("sub_id=kikipunyacerita", formatted)


class TestIndodaxReconciler(unittest.TestCase):
    def setUp(self):
        self.reconciler = IndodaxReconciler()

    @patch("requests.get")
    def test_get_public_ticker(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ticker": {
                "last": "1450000000",
                "buy": "1449000000",
                "sell": "1451000000",
                "high": "1460000000",
                "low": "1430000000",
                "vol_idr": "50000000000"
            },
            "server_time": 1793880000
        }
        mock_get.return_value = mock_resp

        res = self.reconciler.get_public_ticker("btc_idr")
        self.assertEqual(res["last_price"], 1450000000.0)
        self.assertEqual(res["buy"], 1449000000.0)
        self.assertEqual(res["sell"], 1451000000.0)
        self.assertGreater(res["spread"], 0)

    @patch("requests.get")
    def test_market_sentiment_fear_and_greed(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"value": "20", "value_classification": "Extreme Fear", "timestamp": "1793880000"}]
        }
        mock_get.return_value = mock_resp

        sentiment = self.reconciler.get_market_sentiment()
        self.assertEqual(sentiment["value"], 20)
        self.assertEqual(sentiment["classification"], "Extreme Fear")

    @patch("requests.get")
    def test_reconcile_audit_extreme_fear_tuning(self, mock_get):
        # First call ticker, second ticker, third sentiment
        mock_ticker = MagicMock(status_code=200, json=lambda: {"ticker": {"last": "1000000", "buy": "999000", "sell": "1001000"}})
        mock_fng = MagicMock(status_code=200, json=lambda: {"data": [{"value": "18", "value_classification": "Extreme Fear"}]})
        mock_get.side_effect = [mock_fng, mock_ticker, mock_ticker]

        audit = self.reconciler.reconcile_audit()
        self.assertEqual(audit["recommended_allocation"], "ACCUMULATE_80_20_FEAR")


class TestKiBotEmergencyCircuitBreaker(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_actuator.db"
        set_actuator_db_path(self.db_path)
        init_actuator_db()
        self.controller = KiBotController()

    def tearDown(self):
        set_actuator_db_path(None)
        self.temp_dir.cleanup()

    @patch("subprocess.run")
    def test_emergency_stop_and_revert(self, mock_subproc):
        mock_subproc.return_value = MagicMock(returncode=0, stderr="")
        
        # Reset rate limit before test
        record_persistent_rate_limit("kibot_emergency_stop", 0.0, "server1", "kibot-v3-core.service")

        res = self.controller.emergency_stop(reason="Flash crash test")
        self.assertTrue(res.get("success"))
        action_id = res.get("action_id")
        self.assertIsNotNone(action_id)

        # Revert
        undo_res = undo_action(action_id)
        self.assertTrue(undo_res.get("success"))


class TestMobileSentinel(unittest.TestCase):
    def setUp(self):
        self.sentinel = MobileSentinel(serial="40d203460421")

    @patch("subprocess.run")
    def test_read_telemetry_healthy(self, mock_subproc):
        dumpsys_output = (
            "Current Battery Service state:\n"
            "  AC powered: true\n"
            "  USB powered: false\n"
            "  level: 68\n"
            "  scale: 100\n"
            "  temperature: 345\n"
            "  technology: Li-poly\n"
        )
        mock_subproc.side_effect = [
            MagicMock(stdout="List of devices attached\n40d203460421\tdevice\n"),
            MagicMock(stdout=dumpsys_output)
        ]

        t = self.sentinel.read_telemetry()
        self.assertTrue(t["connected"])
        self.assertEqual(t["level"], 68)
        self.assertEqual(t["temp_c"], 34.5)
        self.assertTrue(t["is_charging"])
        self.assertFalse(t["thermal_warning"])
        self.assertFalse(t["overcharge_warning"])

    @patch("subprocess.run")
    def test_thermal_warning_and_overcharge_flags(self, mock_subproc):
        dumpsys_hot = (
            "  AC powered: true\n"
            "  level: 85\n"
            "  temperature: 415\n"
        )
        mock_subproc.side_effect = [
            MagicMock(stdout="List of devices attached\n40d203460421\tdevice\n"),
            MagicMock(stdout=dumpsys_hot)
        ]

        t = self.sentinel.read_telemetry()
        self.assertTrue(t["connected"])
        self.assertEqual(t["level"], 85)
        self.assertEqual(t["temp_c"], 41.5)
        self.assertTrue(t["thermal_warning"])
        self.assertTrue(t["overcharge_warning"])

    @patch.object(MobileSentinel, "get_connected_devices")
    @patch("subprocess.run")
    def test_execute_thermal_protection(self, mock_subproc, mock_devs):
        mock_devs.return_value = {"40d203460421": "device"}
        mock_subproc.return_value = MagicMock(returncode=0)
        res = self.sentinel.execute_thermal_protection()
        self.assertTrue(res["success"])
        self.assertIn("screen_dimmed_to_10", res["actions"])
        self.assertIn("background_apps_killed", res["actions"])


class TestAdaptiveOllamaMemoryGuard(unittest.TestCase):
    @patch("psutil.virtual_memory")
    def test_ollama_bypassed_when_memory_low(self, mock_mem):
        # Simulate Server 1 memory: 952MB total, 300MB available
        mock_mem.return_value = MagicMock(available=300 * 1024 * 1024)
        brain = ZuraBrain()
        res = brain._call_ollama("Test prompt", [], "Test system")
        self.assertIsNone(res, "Ollama must be safely skipped when available RAM < 1.5GB to avoid OOM crash")


class TestWhatIfContingencyEngine(unittest.TestCase):
    def test_new_scenarios_registered_and_executable(self):
        scenarios = [
            "SHOPEE_LINK_DEAD",
            "THREADS_SHADOWBAN_SUSPECTED",
            "POCO_BATTERY_OVERHEAT",
            "ANDROID_CABLE_DISCONNECTED",
            "KIBOT_FLASH_CRASH_PANIC",
            "OCI_IDLE_RECLAIM_RISK"
        ]
        for s in scenarios:
            res = whatif_engine.simulate_what_if(s)
            self.assertEqual(res.get("scenario"), s, f"Scenario {s} must match")
            self.assertIn("autonomous_reflex", res)
            self.assertGreater(len(res["autonomous_reflex"]), 0)


class TestServerWatchdogOCIPulse(unittest.TestCase):
    @patch.object(ServerWatchdog, "_execute_command")
    def test_oci_keepalive_pulse(self, mock_exec):
        mock_exec.return_value = (0, "OK")
        dog = ServerWatchdog()
        res = dog.oci_keepalive_pulse({"id": "server1", "name": "Scanner"})
        self.assertTrue(res["pulse_success"])


if __name__ == "__main__":
    unittest.main()
