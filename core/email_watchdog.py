"""
core/email_watchdog.py - DECOMMISSIONED STUB
Email watchdog has been decommissioned per Zura Charter v2 (Out-of-scope).
All network sockets, IMAP/SMTP handlers, and background tasks are permanently deactivated.
"""

import logging
from typing import List, Dict, Any

logger = logging.getLogger("EmailWatchdog")


class DecommissionedEmailWatchdog:
    """Safe dormant stub preserving interface compatibility without network activity."""

    def is_configured(self) -> bool:
        return False

    def fetch_and_triage_unread(self) -> List[Dict[str, Any]]:
        return []

    async def send_email_alert(self, session, chat_id: int, item: Dict[str, Any]):
        return None

    def send_reply(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        return {"success": False, "error": "Email triage and reply permanently decommissioned per Charter v2"}

    def audit_subscriptions(self, days: int = 60) -> List[Dict[str, Any]]:
        return []


email_watchdog = DecommissionedEmailWatchdog()
