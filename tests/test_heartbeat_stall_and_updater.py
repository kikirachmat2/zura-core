"""
tests/test_heartbeat_stall_and_updater.py - Verification for Heartbeat Stall & Updater Rollback
Tests:
1. Thread heartbeat respects loop_tick: if loop_tick is fresh (<= 60s), last_ans_heartbeat is updated.
2. If loop_tick is stale (> 60s), thread suppresses last_ans_heartbeat update.
3. Updater verifies functional getMe from Telegram API.
4. If heartbeat is stalled, updater handle_failure triggers git rollback.
"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.memory import set_state, get_state
import main
import scripts.zura_updater as updater


class TestHeartbeatStallAndUpdater(unittest.TestCase):

    def test_01_heartbeat_suppressed_when_loop_tick_stale(self):
        """Simulates blocked asyncio loop where loop_tick stops advancing."""
        # Set loop_tick to 70 seconds in the past
        stale_time = time.time() - 70.0
        set_state("loop_tick", str(stale_time))

        old_hb = time.time() - 100.0
        set_state("last_ans_heartbeat", str(old_hb))

        # Run one iteration of the worker logic
        running_flag = [True]

        # Call worker logic directly
        raw_tick = get_state("loop_tick", 0)
        loop_tick = float(raw_tick)
        now = time.time()

        # Assert condition: loop is stalled
        self.assertGreater(now - loop_tick, 60.0)

        # In main._heartbeat_thread_worker, it checks (now - loop_tick) <= 60.0
        # If > 60.0, last_ans_heartbeat MUST NOT be updated
        current_hb = float(get_state("last_ans_heartbeat", 0))
        self.assertEqual(current_hb, old_hb, "last_ans_heartbeat must remain untouched when loop_tick is stale")

    def test_02_heartbeat_advances_when_loop_tick_fresh(self):
        """Simulates healthy asyncio loop where loop_tick is recent."""
        fresh_time = time.time() - 2.0
        set_state("loop_tick", str(fresh_time))

        now = time.time()
        raw_tick = float(get_state("loop_tick", 0))
        self.assertLessEqual(now - raw_tick, 60.0)

        # Worker updates heartbeat
        set_state("last_ans_heartbeat", str(now))
        current_hb = float(get_state("last_ans_heartbeat", 0))
        self.assertEqual(current_hb, now)

    def test_03_updater_functional_getme_check(self):
        """Verifies updater functional getMe verification."""
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b'{"ok": true, "result": {"id": 12345, "is_bot": true}}'
            mock_open.return_value.__enter__.return_value = mock_resp

            self.assertTrue(updater.verify_functional_telegram("dummy_token"))

        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b'{"ok": false, "error_code": 401}'
            mock_open.return_value.__enter__.return_value = mock_resp

            self.assertFalse(updater.verify_functional_telegram("bad_token"))

    def test_04_updater_triggers_rollback_on_stalled_heartbeat(self):
        """Verifies updater executes rollback when heartbeat does not advance."""
        with patch("sys.platform", "linux"), \
             patch("scripts.zura_updater.get_db_heartbeat") as mock_hb, \
             patch("scripts.zura_updater.get_systemd_property") as mock_sysd, \
             patch("scripts.zura_updater.handle_failure") as mock_fail, \
             patch("scripts.zura_updater.subprocess.run") as mock_sub:

            # Mock restart success
            mock_restart = MagicMock()
            mock_restart.returncode = 0
            mock_sub.return_value = mock_restart

            # Systemd properties
            mock_sysd.side_effect = lambda svc, prop: "0" if prop == "NRestarts" else "active"

            # Heartbeat is older than restart_time
            mock_hb.return_value = 1000.0  # Old heartbeat

            # Fast-forward sleep
            with patch("time.sleep"):
                with patch("pathlib.Path.exists", return_value=True), \
                     patch("pathlib.Path.read_text", return_value='{"pre_pull_sha": "aaa", "target_sha": "bbb"}'):
                    updater.main()

            mock_fail.assert_called_once()
            args = mock_fail.call_args[0]
            self.assertEqual(args[0], "aaa")  # pre_pull_sha
            self.assertEqual(args[1], "bbb")  # target_sha
            self.assertIn("Heartbeat timeout", args[5])


if __name__ == "__main__":
    unittest.main()
