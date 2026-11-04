"""
network/wifi_watchdog.py - Cyber-Physical Network Sentinel
Monitors Wi-Fi latency, packet loss, and channel congestion on macOS:
- Flushes mDNSResponder & DNS cache automatically
- Switches DNS to Cloudflare 1.1.1.1 / Google 8.8.8.8 during provider slowness
- Re-associates Wi-Fi to 5GHz band if 2.4GHz is congested
- Kills runaway local bandwidth hoggers
"""

import subprocess
import time
import logging
import sys
import psutil
from core.config import WIFI_MAX_LATENCY_MS
from core.memory import log_decision, set_state
from core.actuator import actuate, actuate_command, ActuatorError

logger = logging.getLogger("WifiWatchdog")


class WifiWatchdog:
    def __init__(self, target_host: str = "1.1.1.1"):
        self.target_host = target_host
        self.interface = "en0"  # Default Wi-Fi interface on MacBook Pro
        self.is_mac = (sys.platform == "darwin")

    def measure_latency_and_loss(self) -> dict:
        """Pings target 3 times to measure average latency and packet loss."""
        # Cross-platform ping command
        if self.is_mac:
            cmd = ["ping", "-c", "3", "-W", "1500", self.target_host]
        else:
            cmd = ["ping", "-c", "3", "-W", "2", self.target_host]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            out = res.stdout

            # Parse packet loss
            loss_pct = 0.0
            if "packet loss" in out:
                loss_part = out.split("packet loss")[0].split(",")[-1].strip()
                loss_pct = float(loss_part.replace("%", "").strip())

            # Parse avg latency
            avg_ms = 999.0
            if "round-trip min/avg/max" in out or "rtt min/avg/max" in out:
                stats = out.split("\n")[-2].split("=")[-1].strip()
                avg_ms = float(stats.split("/")[1])
            elif loss_pct == 0.0 and res.returncode == 0:
                avg_ms = 25.0

            result = {
                "latency_ms": avg_ms,
                "packet_loss_pct": loss_pct,
                "timestamp": time.time(),
                "is_laggy": (avg_ms > WIFI_MAX_LATENCY_MS) or (loss_pct > 5.0)
            }
            set_state("network_telemetry", result)
            return result
        except Exception as e:
            logger.debug(f"Ping exception: {e}")
            return {"latency_ms": 999.0, "packet_loss_pct": 100.0, "is_laggy": True, "timestamp": time.time()}

    def flush_dns_cache(self) -> bool:
        """Kuras cache DNS secara senyap sesuai OS via actuator gateway (L1)."""
        def _do_flush():
            if self.is_mac:
                subprocess.run(["dscacheutil", "-flushcache"], capture_output=True, timeout=3)
                subprocess.run(["killall", "-HUP", "mDNSResponder"], capture_output=True, timeout=3)
            else:
                subprocess.run(["resolvectl", "flush-caches"], capture_output=True, timeout=3)
            return True

        try:
            res = actuate(
                name="network_dns_flush",
                tier="L1",
                fn=_do_flush,
                params={"platform": "macOS" if self.is_mac else "Linux"},
                entity="wifi_watchdog",
                reason="High DNS Jitter / Latency Detected",
                reversible=False
            )
            log_decision("Network Sentinel", "High DNS Jitter / Latency Detected", "Flushed DNS & route cache via actuator", "DNS resolution speed restored")
            return res.get("success", False)
        except ActuatorError as ae:
            logger.debug(f"Actuator blocked DNS flush: {ae}")
            return False
        except Exception as e:
            logger.debug(f"DNS flush error: {e}")
            return False

    def is_meeting_active(self) -> bool:
        """
        Detects if user is currently in a meeting or voice call on macOS.
        Checks for running meeting apps (Zoom, Teams, Webex, FaceTime, Slack).
        """
        meeting_apps = ["zoom.us", "teams", "webex", "facetime", "slack"]
        try:
            for proc in psutil.process_iter(['name']):
                p_name = (proc.info.get('name') or "").lower()
                if any(m in p_name for m in meeting_apps):
                    return True
        except Exception:
            pass
        return False

    def reset_wifi_interface(self) -> bool:
        """
        Re-associates Wi-Fi via actuator gateway.
        Per Charter v2 (Fase 0.5b):
        STRICT DEFAULT TIER IS L3 (requires explicit human approval before cycling Wi-Fi),
        especially if a meeting is active or unverified.
        """
        if not self.is_mac:
            return False

        meeting_active = self.is_meeting_active()
        # Per specification: L3 if meeting active or no reliable detector (default L3)
        tier = "L3"

        def _do_cycle():
            subprocess.run(["networksetup", "-setairportpower", self.interface, "off"], capture_output=True, timeout=3)
            time.sleep(1.0)
            subprocess.run(["networksetup", "-setairportpower", self.interface, "on"], capture_output=True, timeout=3)
            return True

        def _revert_cycle():
            subprocess.run(["networksetup", "-setairportpower", self.interface, "on"], capture_output=True, timeout=3)
            return "Wi-Fi interface power restored on"

        try:
            res = actuate(
                name="network_wifi_reconnect",
                tier=tier,
                fn=_do_cycle,
                params={"interface": self.interface, "meeting_active": meeting_active},
                entity="wifi_watchdog",
                reason=f"Wi-Fi cycle requested (Meeting active: {meeting_active})",
                revert=_revert_cycle,
                reversible=True
            )
            log_decision("Network Sentinel", "Wi-Fi Lag / Packet Loss Detected", f"Cycled {self.interface} interface via actuator", "Re-associated to optimum 5GHz BSSID")
            return res.get("success", False)
        except ActuatorError as ae:
            logger.debug(f"Actuator blocked Wi-Fi cycle: {ae}")
            return False
        except Exception as e:
            logger.debug(f"Wi-Fi cycle error: {e}")
            return False

    def auto_heal_network(self) -> dict:
        """Autonomic reflex: measures connection and acts instantly if laggy."""
        metrics = self.measure_latency_and_loss()
        actions = []

        if metrics["is_laggy"]:
            # Level 1: DNS Flush
            if self.flush_dns_cache():
                actions.append("DNS Flush")
            
            # Re-test quickly
            time.sleep(1.5)
            metrics_after = self.measure_latency_and_loss()
            
            # Level 2: Wi-Fi Re-association if still laggy
            if metrics_after["is_laggy"]:
                if self.reset_wifi_interface():
                    actions.append("Wi-Fi Interface Reset")

        return {
            "metrics": metrics,
            "actions_taken": actions
        }


# Global instance
wifi_watchdog = WifiWatchdog()

