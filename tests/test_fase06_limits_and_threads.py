"""
tests/test_fase06_limits_and_threads.py - Unit Test Suite for Fase 0.6 Revisi
Per Zura Charter v2 & User Directives:
1. Verifies config/limits.env loading and fallback behavior.
2. Verifies file permission enforcement (.env 0600, data/ 0700).
3. Verifies actuator rate limit binding to config variables.
4. Verifies Threads audience listening (sentiment analysis on comments).
5. Verifies Two-Layer AI Story Governance:
   - Layer 1: Contextual narrative drafting
   - Layer 2: QC critic rejecting jarring ad bridges and destructive rage-bait
"""

import os
import sys
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import core.config as config
from core.actuator import set_actuator_db_path, init_actuator_db, actuate, RATE_LIMITS
from ops.threads_governor import ThreadsGovernor


class TestLimitsAndPermissions06(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_root = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_limits_env_parsing(self):
        """Verifies limits.env thresholds are parsed as correct types."""
        self.assertIsInstance(config.MAC_TEMP_MAX_C, float)
        self.assertIsInstance(config.SERVER_RAM_MAX_PCT, float)
        self.assertIsInstance(config.THREADS_DAILY_REPLENISH_CAP, int)
        self.assertIsInstance(config.THREADS_ANGER_CRITICISM_THRESHOLD_PCT, float)
        self.assertGreater(config.THREADS_DAILY_REPLENISH_CAP, 0)

    def test_file_permission_hardening(self):
        """Verifies enforce_file_permissions tightens loose permissions."""
        fake_env = self.test_root / ".env"
        fake_env.write_text("DUMMY_KEY=123\n")
        os.chmod(fake_env, 0o666)  # Insecure permissions

        fake_data = self.test_root / "data"
        fake_data.mkdir()
        os.chmod(fake_data, 0o777)  # Insecure permissions

        with patch("core.config.ENV_PATH", fake_env), patch("core.config.BASE_DIR", self.test_root):
            res = config.enforce_file_permissions(strict=False)
            self.assertIn("tightened_to_0600", res.get("env_permissions", ""))
            self.assertIn("tightened_to_0700", res.get("data_dir_permissions", ""))

            # Verify on disk
            env_mode = fake_env.stat().st_mode & 0o777
            data_mode = fake_data.stat().st_mode & 0o777
            self.assertEqual(env_mode, 0o600)
            self.assertEqual(data_mode, 0o700)

    def test_actuator_rate_limits_dynamically_bound(self):
        """Verifies actuator RATE_LIMITS reflect configured values from config."""
        self.assertEqual(RATE_LIMITS["threads_replenish_queue"], config.RATE_LIMIT_THREADS_REPLENISH_SEC)
        self.assertEqual(RATE_LIMITS["server_restart_service"], config.RATE_LIMIT_SERVER_RESTART_SEC)
        self.assertEqual(RATE_LIMITS["kibot_restart_service"], config.RATE_LIMIT_KIBOT_RESTART_SEC)


class TestThreadsAudienceAndMultiLayerGovernance06(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_root = Path(self.tmp_dir.name)
        self.test_db = self.test_root / "kisahkomisi_test.db"

        # Initialize mock kisahkomisi.db schema
        with sqlite3.connect(str(self.test_db)) as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS product_bank (
                    id INTEGER PRIMARY KEY,
                    category TEXT,
                    name TEXT,
                    description TEXT,
                    affiliate_url TEXT,
                    active INTEGER,
                    times_used INTEGER
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS stories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    topic TEXT,
                    slides_json TEXT,
                    product_name TEXT,
                    product_url TEXT,
                    scheduled_for TEXT,
                    published_at TEXT,
                    threads_media_id TEXT,
                    status TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    qc_score INTEGER,
                    qc_notes TEXT,
                    origin TEXT,
                    format_type TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS auto_replies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    threads_media_id TEXT,
                    comment_id TEXT,
                    author_username TEXT,
                    comment_text TEXT,
                    reply_text TEXT,
                    reply_media_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS story_insights (
                    id INTEGER PRIMARY KEY,
                    story_id INTEGER,
                    views INTEGER,
                    likes INTEGER,
                    replies INTEGER
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS commissions (
                    id INTEGER PRIMARY KEY,
                    amount REAL,
                    status TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS niche_analytics (
                    id INTEGER PRIMARY KEY,
                    niche_tag TEXT,
                    avg_views REAL,
                    is_locked INTEGER
                )
            """)

            # Seed an active product
            cur.execute("""
                INSERT INTO product_bank (category, name, affiliate_url, active, times_used)
                VALUES ('Grooming Pria', 'Kahf Face Wash', 'https://s.shopee.co.id/test', 1, 3)
            """)
            conn.commit()

        # Actuator DB isolation
        self.actuator_db = self.test_root / "actuator.db"
        set_actuator_db_path(self.actuator_db)
        init_actuator_db(self.actuator_db)

        self.governor = ThreadsGovernor()
        self.governor.db_path = self.test_db

    def tearDown(self):
        set_actuator_db_path(None)
        self.tmp_dir.cleanup()

    def test_sentiment_listener_healthy_vs_inflamed(self):
        """Verifies get_audience_sentiment correctly flags healthy vs angry comment threads."""
        with sqlite3.connect(str(self.test_db)) as conn:
            # Seed friendly comments
            conn.execute("INSERT INTO auto_replies (author_username, comment_text) VALUES ('user1', 'asli relate banget bang')")
            conn.execute("INSERT INTO auto_replies (author_username, comment_text) VALUES ('user2', 'wkwk bener juga sih')")
            conn.commit()

        sent_healthy = self.governor.get_audience_sentiment()
        self.assertEqual(sent_healthy["status"], "HEALTHY")
        self.assertEqual(sent_healthy["anger_ratio_pct"], 0.0)

        # Now seed angry/criticism comments
        with sqlite3.connect(str(self.test_db)) as conn:
            conn.execute("INSERT INTO auto_replies (author_username, comment_text) VALUES ('user3', 'ujung-ujungnya jualan lagi anjir, muak gue')")
            conn.execute("INSERT INTO auto_replies (author_username, comment_text) VALUES ('user4', 'cerita fiktif ga nyambung amat sama iklannya')")
            conn.commit()

        sent_inflamed = self.governor.get_audience_sentiment()
        # 2 out of 4 comments contain criticism keywords -> 50% anger ratio >= 25% threshold
        self.assertEqual(sent_inflamed["status"], "HIGH_CRITICISM_OR_ANGER")
        self.assertGreaterEqual(sent_inflamed["anger_ratio_pct"], 25.0)

    def test_layer_2_qc_rejects_jarring_bridge(self):
        """Verifies critique_story penalizes and flags jarring ad bridges."""
        slides = [
            "Gue baru aja dipecat sepihak sama bos kantor.",
            "Semua kerjaan gue diambil alih sama manajer baru.",
            "Btw selingan bentar ya, kemarin banyak yang nanya rekomendasi Kahf Face Wash ini https://shopee.co.id/...",
            "Menurut kalian gue harus lapor disnaker ga?"
        ]
        qc = self.governor.critique_story(slides, "Kahf Face Wash", "Grooming Pria")
        self.assertIn("Abrupt jarring ad bridge detected", qc["notes"])

    def test_layer_2_qc_rejects_destructive_rage_bait(self):
        """Verifies critique_story strictly rejects toxic insults and hostile rage-bait."""
        slides = [
            "Dasar kalian semua sampah masyarakat yang gak berguna.",
            "Kerja gaji UMR tapi gaya selangit mending kalian mati aja.",
            "Beli nih Kahf Face Wash https://shopee.co.id/...",
            "Hujat gue sekarang di kolom komentar kalau gak setuju."
        ]
        qc = self.governor.critique_story(slides, "Kahf Face Wash", "Grooming Pria")
        self.assertFalse(qc["passed"])
        self.assertTrue(qc.get("rage_detected", False))
        self.assertIn("Destructive rage bait detected", qc["reason"])

    def test_layer_2_qc_approves_coherent_relatable_narrative(self):
        """Verifies critique_story approves organic, relatable, non-jarring story."""
        slides = [
            "Tiap balik lembur jam 9 malem naik KRL, muka gue udah kayak amplas kena debu Sudirman.",
            "Mau cuci muka pake sabun mandi kosan malah bikin kulit ketarik dan perih parah.",
            "Untung nemu sabun pembersih Kahf Face Wash ini di https://shopee.co.id/..., busanya lembut dan kotoran polusi langsung luntur tanpa bikin kulit kering.",
            "Kalian yang sering komuter malam biasanya punya ritual cuci muka apa biar ga gampang jerawatan?"
        ]
        qc = self.governor.critique_story(slides, "Kahf Face Wash", "Grooming Pria")
        self.assertTrue(qc["passed"])
        self.assertGreaterEqual(qc["score"], 70)

    @patch("core.brain.brain.think")
    def test_replenish_queue_end_to_end_with_qc_pass(self, mock_think):
        """Verifies full replenishment flow with Layer 2 QC passed stores qc_score."""
        valid_slides = [
            "Tiap balik lembur jam sembilan malam naik KRL, muka gue udah kusam kena debu polusi.",
            "Dulu sering cuek sama muka berminyak, tau-tau komedo numpuk pas mau meeting penting.",
            "Sekarang selalu sedia Kahf Face Wash https://s.shopee.co.id/test di kosan, seger dan gak bikin kulit ketarik.",
            "Warga Threads kalau pulang kerja lembur gini biasanya bersihin muka pakai apa biar tetap seger?"
        ]
        mock_think.return_value = json.dumps(valid_slides)

        res = self.governor.replenish_story_queue()
        self.assertTrue(res["success"])
        self.assertGreaterEqual(res["qc_score"], 70)

        # Verify DB row
        with sqlite3.connect(str(self.test_db)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, status, qc_score, qc_notes FROM stories WHERE id = ?", (res["story_id"],))
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[1], "queued")
            self.assertGreaterEqual(row[2], 70)

    @patch("core.brain.brain.think")
    def test_replenish_queue_rejected_when_qc_fails(self, mock_think):
        """Verifies story is rejected and NOT queued if Layer 2 detects rage bait."""
        bad_slides = [
            "Kalian semua sampah masyarakat yang bisanya cuma ngeluh.",
            "Gue enek liat kalian hidup mending mati aja.",
            "Nih Kahf Face Wash https://s.shopee.co.id/test biar ga dekil.",
            "Ayo baku hantam di komen."
        ]
        mock_think.return_value = json.dumps(bad_slides)

        res = self.governor.replenish_story_queue()
        self.assertFalse(res["success"])
        self.assertIn("QC Rejected", res["reason"])

        # Verify nothing inserted as queued in DB
        with sqlite3.connect(str(self.test_db)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM stories WHERE status = 'queued'")
            count = cur.fetchone()[0]
            self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
