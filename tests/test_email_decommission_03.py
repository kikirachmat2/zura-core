"""
tests/test_email_decommission_03.py - Verification for Step 0.3: Complete Email Decommissioning
Asserts:
1. core/config.py does not contain EMAIL_* config variables.
2. core/email_watchdog.py is a safe, deactivated stub with zero sockets/credentials.
3. main.py does not contain /reply, /subs, or email_watchdog imports.
4. main.py includes independent heartbeat_loop updating last_ans_heartbeat.
5. SQLite system_state is cleaned of legacy email keys.
"""

import unittest
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


class TestEmailDecommission03(unittest.TestCase):

    def test_01_config_has_no_email_keys(self):
        import core.config as cfg
        self.assertFalse(hasattr(cfg, "EMAIL_IMAP_SERVER"))
        self.assertFalse(hasattr(cfg, "EMAIL_USER"))
        self.assertFalse(hasattr(cfg, "EMAIL_PASSWORD"))
        self.assertFalse(hasattr(cfg, "EMAIL_PORT"))

    def test_02_email_watchdog_is_safe_stub(self):
        import core.email_watchdog as ewd
        self.assertFalse(ewd.email_watchdog.is_configured())
        self.assertEqual(ewd.email_watchdog.fetch_and_triage_unread(), [])
        self.assertEqual(ewd.email_watchdog.audit_subscriptions(), [])
        res = ewd.email_watchdog.send_reply("test@example.com", "sub", "body")
        self.assertFalse(res["success"])
        self.assertIn("decommissioned", res["error"].lower())

    def test_03_main_has_no_email_routes_or_imports(self):
        main_source = (BASE_DIR / "main.py").read_text()
        self.assertNotIn("from core.email_watchdog import", main_source)
        self.assertNotIn("import email_watchdog", main_source)
        self.assertNotIn('"/reply"', main_source)
        self.assertNotIn("text.startswith(\"/reply\")", main_source)
        self.assertNotIn('"/subs"', main_source)
        self.assertNotIn("cb_subs", main_source)

    def test_04_main_has_independent_heartbeat_loop(self):
        main_source = (BASE_DIR / "main.py").read_text()
        self.assertIn("async def heartbeat_loop(self):", main_source)
        self.assertIn("last_ans_heartbeat", main_source)
        self.assertIn("self.heartbeat_loop()", main_source)

    def test_05_database_state_cleaned(self):
        db_path = BASE_DIR / "data" / "zura.db"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT key FROM system_state WHERE key IN ('pending_email_drafts', 'processed_email_ids')")
            rows = cur.fetchall()
            conn.close()
            self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
