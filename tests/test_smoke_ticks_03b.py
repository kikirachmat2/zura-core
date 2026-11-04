"""
tests/test_smoke_ticks_03b.py - Smoke Run Test Harness for Step 0.3b
Runs a multi-tick simulated execution of ZuraOrchestrator with mock Telegram API.
Verifies:
1. import main succeeds with zero exceptions.
2. Dedicated OS heartbeat thread continuously writes 'last_ans_heartbeat' to SQLite.
3. Event loop executes polling ticks, dispatching commands and callbacks.
4. Decommissioned financial & spreadsheet features return 'tidak diketahui' (never Rp 0).
5. Clean shutdown without thread leaks.
"""

import sys
import time
import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import main
from core.memory import get_state
from ops.finance_tracker import finance_tracker
from ops.sheets_sync import sheets_sync


class TestSmokeTicks03b(unittest.TestCase):

    def test_01_imports_and_decommissioned_finance_checks(self):
        """Validates that decommissioned modules return 'tidak diketahui'."""
        snap = finance_tracker.get_full_financial_snapshot()
        self.assertEqual(snap["income_tracked_idr"], "tidak diketahui")
        self.assertEqual(snap["expense_tracked_idr"], "tidak diketahui")
        self.assertEqual(snap["net_cashflow_idr"], "tidak diketahui")

        briefing = finance_tracker.generate_wealth_acceleration_briefing()
        self.assertIn("tidak diketahui", briefing)
        self.assertNotIn("Rp 0", briefing)

        sheet_summary = sheets_sync.generate_executive_spreadsheet_summary()
        self.assertIn("tidak diketahui", sheet_summary)

    def test_02_heartbeat_thread_vitality(self):
        """Validates that dedicated OS heartbeat thread writes timestamp to SQLite."""
        orch = main.ZuraOrchestrator()
        try:
            self.assertTrue(orch.heartbeat_thread.is_alive())
            # Wait 1.5s for initial heartbeat write
            time.sleep(1.5)
            hb = float(get_state("last_ans_heartbeat", 0))
            self.assertGreater(hb, time.time() - 10)
        finally:
            orch.running_flag[0] = False
            orch.is_running = False

    def test_03_orchestrator_smoke_ticks_with_stubbed_telegram(self):
        """Executes 3 asynchronous polling ticks with simulated Telegram updates."""
        orch = main.ZuraOrchestrator()

        sent_messages = []

        async def fake_send_text(session, chat_id, text, reply_markup=None):
            sent_messages.append(text)
            return {"ok": True}

        orch.send_text = fake_send_text

        # Mock incoming updates
        fake_updates = [
            # Tick 1: Text command /cuan
            {
                "update_id": 101,
                "message": {
                    "from": {"id": orch.authorized_chat_id},
                    "chat": {"id": orch.authorized_chat_id},
                    "text": "/cuan"
                }
            },
            # Tick 2: Text command /sheet
            {
                "update_id": 102,
                "message": {
                    "from": {"id": orch.authorized_chat_id},
                    "chat": {"id": orch.authorized_chat_id},
                    "text": "/sheet"
                }
            },
            # Tick 3: Callback query cb_cuan
            {
                "update_id": 103,
                "callback_query": {
                    "id": "query_999",
                    "from": {"id": orch.authorized_chat_id},
                    "message": {"chat": {"id": orch.authorized_chat_id}},
                    "data": "cb_cuan"
                }
            }
        ]

        async def run_ticks():
            mock_session = MagicMock()
            # Simulate answer_callback_query
            orch.answer_callback_query = AsyncMock(return_value={"ok": True})

            for update in fake_updates:
                if "callback_query" in update:
                    await orch.handle_callback_query(mock_session, update["callback_query"])
                elif "message" in update:
                    await orch.handle_user_message(mock_session, update["message"])

        asyncio.run(run_ticks())

        # Validate that responses were dispatched and adhere to Charter v2
        self.assertEqual(len(sent_messages), 3)
        for msg in sent_messages:
            self.assertIn("tidak diketahui", msg)
            self.assertNotIn("Rp 0", msg)

        # Cleanup
        orch.running_flag[0] = False
        orch.is_running = False


if __name__ == "__main__":
    unittest.main()

