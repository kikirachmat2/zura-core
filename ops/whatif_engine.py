"""
ops/whatif_engine.py - Zura Autonomous What-If Contingency & Disaster Reflex Engine
Per Zura Charter v2 & Executive Directive:
Maps out edge cases, failure scenarios, and defines deterministic autonomous reflexes
so Zura acts instantly without panicking Bos Kiki:
1. KiBot Nonce Desync / API 429
2. Threads Meta Rate Limit / Token Expiry
3. Server Disk / RAM Exhaustion (>85%)
4. Mac Thermal Throttling (>62°C)
5. Wi-Fi Instability During Live Meeting
6. GitOps Breaking Commit / Syntax Errors
7. Financial Story Arithmetic / Geographic Hallucination
8. Prompt Injection / SSRF Evasion Attempt
"""

import os
import sys
import time
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.actuator import actuate, is_system_paused
from core.memory import log_decision, get_state, set_state

logger = logging.getLogger("WhatIfEngine")


class WhatIfContingencyEngine:
    def __init__(self):
        self.scenarios_registry = {
            "KIBOT_NONCE_DESYNC": self.handle_kibot_nonce_desync,
            "KIBOT_API_TIMEOUT": self.handle_kibot_api_timeout,
            "THREADS_META_429": self.handle_threads_meta_429,
            "SERVER_DISK_EXHAUSTION": self.handle_server_disk_exhaustion,
            "SERVER_RAM_SPIKE": self.handle_server_ram_spike,
            "MAC_THERMAL_THROTTLING": self.handle_mac_thermal_throttling,
            "WIFI_MEETING_ACTIVE": self.handle_wifi_meeting_active,
            "GITOPS_BROKEN_SYNTAX": self.handle_gitops_broken_syntax,
            "STORY_MATH_MISMATCH": self.handle_story_math_mismatch,
            "PROMPT_INJECTION_DETECTED": self.handle_prompt_injection_detected
        }

    def simulate_what_if(self, scenario_key: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Simulates an edge-case scenario and returns Zura's predetermined autonomous contingency protocol.
        """
        if scenario_key not in self.scenarios_registry:
            return {
                "success": False,
                "error": f"Scenario '{scenario_key}' not in contingency registry.",
                "known_scenarios": list(self.scenarios_registry.keys())
            }

        handler = self.scenarios_registry[scenario_key]
        return handler(context or {})

    # =========================================================================
    # 1. KIBOT CONTINGENCIES
    # =========================================================================
    def handle_kibot_nonce_desync(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        What if Indodax rejects order with 'Invalid nonce' / timestamp desync?
        Action: Instantly step server chrony NTP clock on Server 1 and retry order without waking Kiki.
        """
        return {
            "scenario": "KIBOT_NONCE_DESYNC",
            "risk_level": "HIGH",
            "what_if": "Indodax rejects orders due to local server clock drift (nonce desync).",
            "autonomous_reflex": [
                "1. Pause next scheduled DCA order by 15s.",
                "2. Execute 'sudo chronyd -q' / 'chronyc makestep' to synchronize millisecond clock.",
                "3. Verify NTP offset < 2ms.",
                "4. Re-issue failed DCA order with fresh millisecond nonce.",
                "5. Log outcome and report summary in morning executive digest."
            ],
            "requires_human_approval": False,
            "contingency_tier": "L1",
            "rollback_plan": "If NTP fails twice, trip circuit breaker and send single high-priority Telegram alert."
        }

    def handle_kibot_api_timeout(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        What if Indodax API times out or returns HTTP 502/504 during order placement?
        """
        return {
            "scenario": "KIBOT_API_TIMEOUT",
            "risk_level": "HIGH",
            "what_if": "Exchange endpoint times out during DCA execution.",
            "autonomous_reflex": [
                "1. DO NOT immediately re-send buy order to prevent double-spending.",
                "2. Query /trade_history and /open_orders using private API to verify if order filled.",
                "3. If order unfulfilled after 10m, cancel unfilled limit order.",
                "4. If unexecuted, postpone cycle by 30 minutes with exponential jitter.",
                "5. Ensure total daily allocation remains strictly within MAX_SINGLE_TRADE_IDR."
            ],
            "requires_human_approval": False,
            "contingency_tier": "L1",
            "rollback_plan": "Restore pre-order balance state and abort DCA until next scheduled window."
        }

    # =========================================================================
    # 2. THREADS CONTINGENCIES
    # =========================================================================
    def handle_threads_meta_429(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        What if Meta Threads API returns HTTP 429 (Rate Limit Exceeded)?
        """
        return {
            "scenario": "THREADS_META_429",
            "risk_level": "MEDIUM",
            "what_if": "Threads rate limits account for posting or auto-replying.",
            "autonomous_reflex": [
                "1. Immediately halt outgoing publishing and auto-replies.",
                "2. Enforce 60-90 minute jitter cooling sleep in memory & database.",
                "3. Postpone scheduled stories in queue without deleting them.",
                "4. When cooling expires, resume with 1 single organic test post before affiliate posts.",
                "5. Log rate-limit duration to niche_analytics."
            ],
            "requires_human_approval": False,
            "contingency_tier": "L1",
            "rollback_plan": "Retain story queue in SQLite; zero data loss."
        }

    # =========================================================================
    # 3. SERVER RESOURCE CONTINGENCIES
    # =========================================================================
    def handle_server_disk_exhaustion(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        What if Server 1 or 2 disk usage exceeds 85%?
        """
        return {
            "scenario": "SERVER_DISK_EXHAUSTION",
            "risk_level": "HIGH",
            "what_if": "OCI 50GB disk approaches capacity, threatening database write failure.",
            "autonomous_reflex": [
                "1. Clean journalctl logs: 'journalctl --vacuum-size=200M'.",
                "2. Remove obsolete apt cache and packages: 'apt-get autoremove -y && apt-get clean'.",
                "3. Rotate and prune application logs (>14 days).",
                "4. Execute SQLite PRAGMA incremental_vacuum on zura.db and kisahkomisi.db.",
                "5. If usage still >80%, alert Bos Kiki via Telegram with exact disk breakdown."
            ],
            "requires_human_approval": False,
            "contingency_tier": "L1",
            "rollback_plan": "Never touch .env, backups/, or active database files."
        }

    def handle_server_ram_spike(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        What if PM2 or Node.js process experiences memory leak (>150MB)?
        """
        return {
            "scenario": "SERVER_RAM_SPIKE",
            "risk_level": "MEDIUM",
            "what_if": "Node.js / PM2 bot consumes runaway memory.",
            "autonomous_reflex": [
                "1. Execute graceful PM2 reload: 'pm2 reload <app_name>'.",
                "2. Force Node.js V8 garbage collection via restart.",
                "3. Verify process returns to healthy PID and memory < 80MB.",
                "4. Log restart in actuator_audit_log."
            ],
            "requires_human_approval": False,
            "contingency_tier": "L2",
            "rollback_plan": "PM2 automatically falls back to previous worker if reload fails."
        }

    # =========================================================================
    # 4. MAC THERMAL & PROCESS CONTINGENCIES
    # =========================================================================
    def handle_mac_thermal_throttling(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        What if MacBook Pro temperature exceeds 62°C?
        """
        return {
            "scenario": "MAC_THERMAL_THROTTLING",
            "risk_level": "MEDIUM",
            "what_if": "Mac CPU heats up due to rogue background compilation or runaway browser tabs.",
            "autonomous_reflex": [
                "1. Identify top 3 non-foreground CPU consumers via psutil.",
                "2. Verify target process is NOT the foreground active app.",
                "3. Renice background process priority to +10 (low priority).",
                "4. Vacuum transient cache (Safari/Chrome/Spotify) from allowed whitelist.",
                "5. Cool down verified once temperature drops below 55°C."
            ],
            "requires_human_approval": False,
            "contingency_tier": "L1",
            "rollback_plan": "Revert process niceness to 0 via /undo if user requests."
        }

    def handle_wifi_meeting_active(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        What if Wi-Fi latency spikes while Bos Kiki is on a Zoom/Meet/FaceTime call?
        """
        return {
            "scenario": "WIFI_MEETING_ACTIVE",
            "risk_level": "CRITICAL",
            "what_if": "Network latency spikes during an active business video/voice call.",
            "autonomous_reflex": [
                "1. STRICT MEETING GUARD: NEVER toggle, reconnect, or reset Wi-Fi interface.",
                "2. Perform silent DNS flush only ('dscacheutil -flushcache').",
                "3. Throttle background cloud sync processes (Dropbox, OneDrive, Steam) via renice.",
                "4. Suppress non-critical notifications to preserve focus.",
                "5. Maintain seamless audio/video connection without dropping the call."
            ],
            "requires_human_approval": True,
            "contingency_tier": "L3 (Interface Reconnect Blocked)",
            "rollback_plan": "Do nothing to physical interfaces until call process terminates."
        }

    # =========================================================================
    # 5. GITOPS CONTINGENCIES
    # =========================================================================
    def handle_gitops_broken_syntax(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        What if a git pull contains a syntax error or breaking dependency?
        """
        return {
            "scenario": "GITOPS_BROKEN_SYNTAX",
            "risk_level": "CRITICAL",
            "what_if": "Pushed commit has broken syntax or missing packages.",
            "autonomous_reflex": [
                "1. Test-import all modified files in isolated subprocess BEFORE touching zura.service.",
                "2. If import exit code != 0, ABORT apply immediately.",
                "3. Hard reset git tree back to pre-update SHA.",
                "4. Restore original virtualenv packages from pip freeze backup.",
                "5. Send detailed post-mortem diff alert to Bos Kiki Telegram."
            ],
            "requires_human_approval": False,
            "contingency_tier": "L1 (Auto-Rollback)",
            "rollback_plan": "Automatic atomic git reset + service restart on original SHA."
        }

    # =========================================================================
    # 6. CONTENT TRUTH CONTINGENCIES
    # =========================================================================
    def handle_story_math_mismatch(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        What if draft story contains incorrect arithmetic or geographic hallucination?
        """
        return {
            "scenario": "STORY_MATH_MISMATCH",
            "risk_level": "HIGH",
            "what_if": "Story has salary breakdown deficit or claims KRL in Surabaya.",
            "autonomous_reflex": [
                "1. Deterministic reality_verifier detects arithmetic imbalance or transit flaw.",
                "2. Immediately REJECT draf from entering queue (is_approved: False).",
                "3. Zura Editorial Gatekeeper auto-rewrites numbers so sum(allocations) == stated_salary exactly.",
                "4. Correct local transit terms to verified regional realities.",
                "5. Only queue mathematically airtight revised_slides into database."
            ],
            "requires_human_approval": False,
            "contingency_tier": "L1",
            "rollback_plan": "Discard flawed draft; keep queue clean."
        }

    def handle_prompt_injection_detected(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        What if external web page or netizen comment contains prompt injection attempt?
        """
        return {
            "scenario": "PROMPT_INJECTION_DETECTED",
            "risk_level": "HIGH",
            "what_if": "Comment or web content attempts to hijack LLM system instructions.",
            "autonomous_reflex": [
                "1. SafeFetch strips breakout tags (</untrusted_web>).",
                "2. autoReplyEngine regex detects 'ignore previous', 'jailbreak', 'system prompt'.",
                "3. Auto-reply is cancelled or replaced with authentic witty retort: 'wkwk mau nge-jailbreak ya bang?'.",
                "4. Prevent compromised text from being executed by actuator.",
                "5. Maintain Zura system prompt boundaries intact."
            ],
            "requires_human_approval": False,
            "contingency_tier": "L1",
            "rollback_plan": "Drop untrusted payload completely."
        }


# Global contingency engine instance
whatif_engine = WhatIfContingencyEngine()

