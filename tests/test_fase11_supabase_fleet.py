"""
tests/test_fase11_supabase_fleet.py - Unit Tests for Supabase Cloud Fleet Hub
Verifies connection resiliency, fleet telemetry, event bus, staging, and KiBot ledger sync.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.supabase_hub import (
    get_pg_connection,
    update_fleet_heartbeat,
    get_fleet_telemetry,
    publish_event,
    fetch_pending_events,
    mark_event_processed,
    stage_threads_post,
    submit_deliberation_verdict,
    record_kibot_execution,
    get_latest_kibot_portfolio,
    record_capital_flywheel,
    record_executive_decision
)


class TestSupabaseFleet(unittest.TestCase):

    def test_supabase_connection_graceful_fail_without_credentials(self):
        """Ensures get_pg_connection returns None gracefully if no password."""
        with patch("core.supabase_hub.SUPABASE_DB_PASS", ""):
            conn = get_pg_connection()
            self.assertIsNone(conn)

    def test_update_fleet_heartbeat_offline_fallback(self):
        """Ensures update_fleet_heartbeat returns False without throwing when offline."""
        with patch("core.supabase_hub.get_pg_connection", return_value=None):
            ok = update_fleet_heartbeat("zura", "Zura", "COO", "ONLINE")
            self.assertFalse(ok)

    def test_publish_and_fetch_events_offline_fallback(self):
        """Ensures bus methods return empty list or None when database is unreachable."""
        with patch("core.supabase_hub.get_pg_connection", return_value=None):
            ev_id = publish_event("zura", "threads", "test", "PING", {})
            self.assertIsNone(ev_id)

            events = fetch_pending_events("zura")
            self.assertEqual(events, [])

            marked = mark_event_processed(999, "zura")
            self.assertFalse(marked)

    def test_stage_threads_post_offline_fallback(self):
        """Ensures staging methods handle database outages safely."""
        with patch("core.supabase_hub.get_pg_connection", return_value=None):
            staging_id = stage_threads_post(1, 1, "19:30", "test draft", "Topic", "Fan", "http://shopee")
            self.assertIsNone(staging_id)

            v_ok = submit_deliberation_verdict(1, "APPROVED", "Good", "approved text")
            self.assertFalse(v_ok)

    def test_kibot_and_flywheel_offline_fallback(self):
        """Ensures KiBot ledger records handle offline state without unhandled exception."""
        with patch("core.supabase_hub.get_pg_connection", return_value=None):
            k_id = record_kibot_execution("btc_idr", "DCA_BUY", 100000, 1100000000, 0.00009)
            self.assertIsNone(k_id)

            port = get_latest_kibot_portfolio()
            self.assertIsNone(port)

            fw_ok = record_capital_flywheel("SHOPEE", "KIBOT", 50000, "Reinvest")
            self.assertFalse(fw_ok)

            dec_ok = record_executive_decision("STRATEGY", "Trigger", "Decision", "Outcome")
            self.assertFalse(dec_ok)

    def test_live_supabase_operations_if_configured(self):
        """If live credentials exist, run round-trip verification on Supabase."""
        from core.config import SUPABASE_DB_PASS
        if not SUPABASE_DB_PASS:
            self.skipTest("No live Supabase credentials configured")

        # 1. Heartbeat
        hb_ok = update_fleet_heartbeat("zura", "ZURA Autonomous Personal AI", "COO_LEADER", "ONLINE", "TestRunner")
        self.assertTrue(hb_ok)

        # 2. Telemetry list
        tele = get_fleet_telemetry()
        self.assertGreaterEqual(len(tele), 1)
        bot_ids = [t["bot_id"] for t in tele]
        self.assertIn("zura", bot_ids)

        # 3. Publish & Mark Event
        ev_id = publish_event("zura", "threads", "test", "TEST_PING", {"ping": 123}, telegram_broadcast=False)
        self.assertIsNotNone(ev_id)
        marked = mark_event_processed(ev_id, "zura", "DISMISSED")
        self.assertTrue(marked)


if __name__ == "__main__":
    unittest.main()
