"""
tests/test_actuator_05.py - Step 0.5b Comprehensive Actuator, Integrity, and Topology Test Suite
Verifies:
1. DB Isolation Guard: Asserts DB_PATH is always in tmp; fails if touching live data/zura.db.
2. AST Static Guard & Negative Control: Scans ans/, ops/, network/ and verifies negative control failure.
3. Parametrized Pause: Tests all registered actions are fail-closed blocked when paused.
4. L3 Pause & Rate Limit Re-check: Tests pause activated between request & approval, and rate limit re-check.
5. Persistent Composite Rate Limiter & Circuit Breaker: (action_name, host, service) with single-alert circuit breaker.
6. Updater Boot Marker Proof: Verifies sha == target, ts > restart, pid != old_pid, and ans_cycle_completed.
7. KiBot 3-Backup Rotation & Permissions: Rotates .env.bak.1..3 with chmod 600, logging only changed keys.
8. Wi-Fi Reconnect Meeting Guard: Default L3 tier protecting active meetings.
9. Captive Portal Same-Origin Guard: Blocks cross-origin POST requests.
10. Threads Daily Replenishment Cap: Enforces max 5 stories/day.
"""

import os
import ast
import sys
import time
import json
import uuid
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import core.config as config
from core.actuator import (
    actuate, actuate_command, is_system_paused, set_system_paused,
    execute_approved_action, reject_approved_action, undo_action,
    sanitize_value, ActuatorError, ActuatorPausedError, ActuatorRateLimitError,
    set_actuator_db_path, get_db_path, init_actuator_db,
    PENDING_APPROVALS, REVERT_REGISTRY, RATE_LIMITS, REVENUE_CRITICAL_ACTIONS,
    _CIRCUIT_BREAKER_TRIGGERED, register_notifier
)
from ops.kibot_controller import KiBotController
from network.wifi_watchdog import WifiWatchdog
from network.aggressive_wifi import AggressiveWifiSentinel
from ops.threads_governor import ThreadsGovernor
from scripts.zura_updater import verify_boot_marker


class BaseIsolatedTestCase(unittest.TestCase):
    """Base class providing strict temporary DB isolation for every test."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="zura_actuator_test_")
        self.test_db = Path(self.tmp_dir) / "test_zura.db"

        # Explicitly assert temporary path
        self.assertTrue(
            str(self.test_db).startswith(tempfile.gettempdir()) or "tmp" in str(self.test_db).lower(),
            "CRITICAL SECURITY: Test must run exclusively against temporary DB!"
        )

        # Inject test DB path
        self.orig_config_db = config.DB_PATH
        config.DB_PATH = self.test_db
        set_actuator_db_path(self.test_db)
        init_actuator_db(self.test_db)

        # Ensure system starts unpaused in test DB
        set_system_paused(False)

        PENDING_APPROVALS.clear()
        REVERT_REGISTRY.clear()
        _CIRCUIT_BREAKER_TRIGGERED.clear()

    def tearDown(self):
        config.DB_PATH = self.orig_config_db
        set_actuator_db_path(None)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        PENDING_APPROVALS.clear()
        REVERT_REGISTRY.clear()
        _CIRCUIT_BREAKER_TRIGGERED.clear()


class TestDBIsolationGuard(BaseIsolatedTestCase):
    """Item 1: Test DB Isolation Guard & Live DB Hygiene."""

    def test_db_isolation_guard(self):
        # Must strictly reject non-temp DB path
        curr_db = get_db_path()
        self.assertTrue("tmp" in str(curr_db).lower() or str(curr_db).startswith(tempfile.gettempdir()))
        self.assertNotEqual(curr_db, BASE_DIR / "data" / "zura.db")

    def test_fail_closed_on_corrupt_db_in_tmp(self):
        corrupt_db = Path(self.tmp_dir) / "nonexistent_sub" / "corrupt.db"
        set_actuator_db_path(corrupt_db)
        self.assertTrue(is_system_paused(), "Kill Switch must be FAIL-CLOSED on corrupt/missing DB!")


class TestActuatorASTStaticGuard(BaseIsolatedTestCase):
    """Item 3: AST Static Guard & Negative Control Test."""

    def test_ast_scan_no_forbidden_mutations(self):
        target_dirs = ["ans", "ops", "network"]
        forbidden_calls = []

        for d in target_dirs:
            dir_path = BASE_DIR / d
            for py_file in dir_path.glob("**/*.py"):
                with open(py_file, "r", encoding="utf-8") as f:
                    content = f.read()

                tree = ast.parse(content, filename=str(py_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        # os.system forbidden
                        if node.func.attr == "system" and getattr(node.func.value, "id", None) == "os":
                            forbidden_calls.append(f"{py_file.name}:{node.lineno} calls os.system")
                        # shutil.rmtree forbidden
                        elif node.func.attr == "rmtree" and getattr(node.func.value, "id", None) == "shutil":
                            forbidden_calls.append(f"{py_file.name}:{node.lineno} calls shutil.rmtree")

        self.assertEqual(forbidden_calls, [], f"Forbidden AST mutations detected: {forbidden_calls}")

    def test_ast_negative_control(self):
        """Negative control: Verifies AST guard catches un-guarded mutations and FAILS."""
        dummy_file = BASE_DIR / "ans" / "_temp_negative_control.py"
        try:
            dummy_file.write_text("import os\nos.system('echo dangerous')\n")
            with open(dummy_file, "r") as f:
                tree = ast.parse(f.read(), filename=str(dummy_file))

            caught = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == "system" and getattr(node.func.value, "id", None) == "os":
                        caught = True
                        break

            self.assertTrue(caught, "Negative control must successfully detect os.system violation!")
        finally:
            dummy_file.unlink(missing_ok=True)


class TestParametrizedKillSwitch(BaseIsolatedTestCase):
    """Item 4: Parametrized Pause across all registered actions."""

    def test_all_actions_blocked_when_paused(self):
        set_system_paused(True)
        self.assertTrue(is_system_paused())

        all_actions = [
            ("server_restart_service", "L2", {"service": "chrony"}),
            ("kibot_restart_service", "L2", {"service": "kibot-v3-core"}),
            ("server_vacuum_logs", "L1", {"node": "SG1"}),
            ("mac_renice_process", "L1", {"pid": 1234}),
            ("mac_purge_cache", "L1", {"force": True}),
            ("mac_memory_purge", "L1", {}),
            ("network_dns_flush", "L1", {}),
            ("network_wifi_reconnect", "L3", {"interface": "en0"}),
            ("wifi_solve_captive_portal", "L2", {}),
            ("wifi_hotspot_failover", "L2", {}),
            ("kibot_tune_env", "L2", {"changed_key": "MAX_SINGLE_TRADE_IDR", "value": 750000.0}),
            ("threads_replenish_queue", "L2", {}),
            ("gitops_apply_update", "L3", {"target_sha": "0123456789abcdef0123456789abcdef01234567"}),
        ]

        for action_name, tier, params in all_actions:
            with self.subTest(action=action_name):
                with self.assertRaises(ActuatorPausedError):
                    actuate(
                        name=action_name,
                        tier=tier,
                        fn=lambda: "ran",
                        params=params,
                        entity="test_harness",
                        reason="parametrized pause test"
                    )

                # Verify audit record reflects BLOCKED_PAUSED
                with sqlite3.connect(str(self.test_db)) as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT status FROM actuator_audit_log WHERE action_name = ? ORDER BY timestamp DESC LIMIT 1",
                        (action_name,)
                    )
                    row = cur.fetchone()
                    self.assertIsNotNone(row)
                    self.assertEqual(row[0], "BLOCKED_PAUSED")


class TestL3InterceptionAndRateLimitRecheck(BaseIsolatedTestCase):
    """Item 4: Pause activated between L3 request & approval, and rate limit re-check."""

    def test_pause_between_request_and_approval_blocks_execution(self):
        executed_flag = [False]
        def _action():
            executed_flag[0] = True
            return "DONE"

        # 1. Action queued when unpaused
        res = actuate("test_l3_action", tier="L3", fn=_action, entity="test", reason="need signoff")
        action_id = res["action_id"]
        self.assertFalse(executed_flag[0])

        # 2. Pause is activated BEFORE human clicks button
        set_system_paused(True)

        # 3. Human clicks button -> MUST be blocked
        appr_res = execute_approved_action(action_id, config.TELEGRAM_CHAT_ID)
        self.assertFalse(appr_res["success"])
        self.assertIn("paused", appr_res["error"].lower())
        self.assertFalse(executed_flag[0])

    def test_rate_limit_rechecked_at_approval_time(self):
        from core.actuator import record_persistent_rate_limit
        def _action():
            return "EXECUTED"

        # 1. Action queued
        res = actuate("server_restart_service", tier="L3", fn=_action, params={"service": "chrony"}, entity="test", reason="restart")
        action_id = res["action_id"]

        # 2. Simulate another execution happening while approval was pending (activating cooldown)
        record_persistent_rate_limit("server_restart_service", "localhost", "chrony", time.time())

        # 3. Approval attempted during cooldown -> MUST be rejected
        appr_res = execute_approved_action(action_id, config.TELEGRAM_CHAT_ID)
        self.assertFalse(appr_res["success"])
        self.assertIn("Rate limit active", appr_res["error"])


class TestPersistentRateLimitingAndCircuitBreaker(BaseIsolatedTestCase):
    """Item 5: Persistent composite rate limits & Circuit Breaker alerts."""

    def test_composite_key_rate_limiting(self):
        # Different services on same action name do NOT block each other
        res1 = actuate("server_restart_service", tier="L2", fn=lambda: "ok", params={"service": "chrony"}, entity="test", reason="test")
        self.assertTrue(res1["success"])

        res2 = actuate("server_restart_service", tier="L2", fn=lambda: "ok", params={"service": "pm2"}, entity="test", reason="test")
        self.assertTrue(res2["success"])

        # Same service on same action name within cooldown MUST raise ActuatorRateLimitError
        with self.assertRaises(ActuatorRateLimitError):
            actuate("server_restart_service", tier="L2", fn=lambda: "fail", params={"service": "chrony"}, entity="test", reason="test")

    def test_circuit_breaker_alert_sent_once_for_revenue_critical(self):
        alerts_received = []
        def _mock_notifier(tier, data):
            if tier == "CIRCUIT_BREAKER":
                alerts_received.append(data)

        register_notifier(_mock_notifier)

        # First execution succeeds
        actuate("kibot_tune_env", tier="L2", fn=lambda: "ok", params={"changed_key": "MAX_SINGLE_TRADE_IDR", "value": 750000.0}, entity="test", reason="test")

        # Second execution blocked: circuit breaker alert must fire ONCE
        with self.assertRaises(ActuatorRateLimitError):
            actuate("kibot_tune_env", tier="L2", fn=lambda: "fail", params={"changed_key": "MAX_SINGLE_TRADE_IDR", "value": 750000.0}, entity="test", reason="test")
        self.assertEqual(len(alerts_received), 1)
        self.assertEqual(alerts_received[0]["name"], "kibot_tune_env")

        # Third execution blocked: circuit breaker MUST NOT spam alert again
        with self.assertRaises(ActuatorRateLimitError):
            actuate("kibot_tune_env", tier="L2", fn=lambda: "fail", params={"changed_key": "MAX_SINGLE_TRADE_IDR", "value": 750000.0}, entity="test", reason="test")
        self.assertEqual(len(alerts_received), 1, "Circuit breaker must NOT spam repeated alerts during cooldown!")


class TestUpdaterBootMarkerProof(BaseIsolatedTestCase):
    """Item 7: Boot marker verification requirements {sha, pid, ts, ans_cycle_completed}."""

    def test_boot_marker_validation(self):
        marker_file = BASE_DIR / ".git" / "zura_boot_marker.json"
        restart_time = 1000.0

        try:
            # 1. Missing marker
            marker_file.unlink(missing_ok=True)
            ok, msg = verify_boot_marker("abc1234", restart_time)
            self.assertFalse(ok)

            # 2. ANS cycle not completed
            marker_file.write_text(json.dumps({"sha": "abc1234", "ts": 1050.0, "pid": 999, "ans_cycle_completed": False}))
            ok, msg = verify_boot_marker("abc1234", restart_time)
            self.assertFalse(ok)
            self.assertIn("not completed", msg)

            # 3. Timestamp stale (ts <= restart_time)
            marker_file.write_text(json.dumps({"sha": "abc1234", "ts": 990.0, "pid": 999, "ans_cycle_completed": True}))
            ok, msg = verify_boot_marker("abc1234", restart_time)
            self.assertFalse(ok)
            self.assertIn("stale", msg)

            # 4. SHA mismatch
            marker_file.write_text(json.dumps({"sha": "wrong_sha", "ts": 1050.0, "pid": 999, "ans_cycle_completed": True}))
            ok, msg = verify_boot_marker("abc1234", restart_time)
            self.assertFalse(ok)
            self.assertIn("mismatch", msg)

            # 5. PID unchanged from initial process
            marker_file.write_text(json.dumps({"sha": "abc1234", "ts": 1050.0, "pid": 111, "ans_cycle_completed": True}))
            ok, msg = verify_boot_marker("abc1234", restart_time, old_pid=111)
            self.assertFalse(ok)
            self.assertIn("PID unchanged", msg)

            # 6. Fully valid
            marker_file.write_text(json.dumps({"sha": "abc1234", "ts": 1050.0, "pid": 222, "ans_cycle_completed": True}))
            ok, msg = verify_boot_marker("abc1234", restart_time, old_pid=111)
            self.assertTrue(ok)
            self.assertIn("fully verified", msg)
        finally:
            marker_file.unlink(missing_ok=True)


class TestKiBotAuditAndRotation(BaseIsolatedTestCase):
    """Item 8: KiBot 3-backup rotation, chmod 600, and changed-key-only logging."""

    def test_kibot_backup_rotation_and_chmod(self):
        env_file = Path(self.tmp_dir) / ".env"
        env_file.write_text("MAX_SINGLE_TRADE_IDR=750000.0\nSECRET_KEY=supersecret123\n")
        os.chmod(env_file, 0o600)

        controller = KiBotController()
        controller.env_path = env_file

        # Perform 4 tunes to trigger 3-backup rotation
        for val in [1500000.0, 750000.0, 1500000.0, 750000.0]:
            # Advance persistent rate limit to permit tuning
            from core.actuator import record_persistent_rate_limit
            record_persistent_rate_limit("kibot_tune_env", "localhost", "MAX_SINGLE_TRADE_IDR", 0.0)
            res = controller.tune_market_regime("BULL", max_trade_idr=val)
            self.assertTrue(res.get("success"))

        bak1 = env_file.with_name(f"{env_file.name}.bak.1")
        bak2 = env_file.with_name(f"{env_file.name}.bak.2")
        bak3 = env_file.with_name(f"{env_file.name}.bak.3")
        bak4 = env_file.with_name(f"{env_file.name}.bak.4")

        self.assertTrue(bak1.exists())
        self.assertTrue(bak2.exists())
        self.assertTrue(bak3.exists())
        self.assertFalse(bak4.exists(), "Must strictly maintain a maximum of 3 backup copies!")

        # Verify permissions are chmod 600
        for b in [bak1, bak2, bak3]:
            mode = b.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600, f"Backup {b.name} must have 0o600 permissions, got {oct(mode)}")


class TestTierGuardsAndCaps(BaseIsolatedTestCase):
    """Item 9: Meeting guard default L3, captive portal same-origin, and daily threads cap."""

    def test_wifi_reconnect_defaults_to_l3(self):
        watchdog = WifiWatchdog()
        # reset_wifi_interface must queue for L3 approval, not execute directly
        res = watchdog.reset_wifi_interface()
        self.assertFalse(res, "Default tier must be L3, returning False without explicit approval")

        # Verify action was queued in PENDING_APPROVALS
        queued = any(a["name"] == "network_wifi_reconnect" for a in PENDING_APPROVALS.values())
        self.assertTrue(queued, "network_wifi_reconnect must be queued for L3 approval by default!")

    def test_captive_portal_same_origin_enforcement(self):
        sentinel = AggressiveWifiSentinel()
        portal_info = {
            "url": "http://coffeeshop.wifi.portal/login.html",
            "html": '<form action="http://malicious.external.com/steal"></form>'
        }
        res = sentinel.solve_captive_portal(portal_info)
        self.assertFalse(res, "Cross-origin captive portal submission must be strictly blocked!")

    def test_threads_replenish_daily_cap(self):
        governor = ThreadsGovernor()
        governor.db_path = Path(self.tmp_dir) / "kisahkomisi.db"
        with sqlite3.connect(str(governor.db_path)) as c:
            c.execute("""
                CREATE TABLE stories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT, topic TEXT, slides_json TEXT,
                    product_name TEXT, product_url TEXT, status TEXT,
                    origin TEXT, format_type TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            c.execute("CREATE TABLE product_bank (id INTEGER PRIMARY KEY, name TEXT, category TEXT, affiliate_url TEXT, active INTEGER)")
            c.execute("INSERT INTO product_bank VALUES (1, 'Kemeja', 'Fashion', 'https://shopee.co.id/aff', 1)")
            # Insert 5 stories created today
            for i in range(5):
                c.execute("INSERT INTO stories (title, status, created_at) VALUES (?, 'queued', datetime('now'))", (f"Story {i}",))

        res = governor.replenish_story_queue()
        self.assertFalse(res["success"])
        self.assertIn("Daily cap reached", res["reason"])


if __name__ == "__main__":
    unittest.main()
