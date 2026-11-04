"""
network/aggressive_wifi.py - Zura Aggressive Internet & Captive Portal Solver
Ensures MacBook Pro 2020 stays aggressively connected wherever Kiki goes:
1. Detects & auto-bypasses coffeeshop Captive Portals (auto-POST splash agreement)
2. Auto-connects to saved preferred coffeeshop Wi-Fis
3. Autonomous failover to Phone Personal Hotspot (via ADB / networksetup) when public Wi-Fi fails
"""

import re
import time
import socket
import logging
import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse
import urllib.request
import urllib.parse
from http.cookiejar import CookieJar

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.config import PERSONAL_HOTSPOT_SSID, PERSONAL_HOTSPOT_PASS
from core.memory import log_decision, set_state
from core.actuator import actuate, ActuatorError

logger = logging.getLogger("AggressiveWifi")

CAPTIVE_CHECK_URL = "http://captive.apple.com/hotspot-detect.html"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"


class AggressiveWifiSentinel:
    def __init__(self, interface: str = "en0"):
        self.interface = interface
        self.cj = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def has_internet(self) -> bool:
        """Pings DNS roots to test raw IP connectivity."""
        for host in ["1.1.1.1", "8.8.8.8"]:
            try:
                cmd = ["ping", "-c", "2", "-W", "1200", host]
                res = subprocess.run(cmd, capture_output=True, timeout=3)
                if res.returncode == 0:
                    return True
            except Exception:
                pass
        return False

    def check_captive_portal(self) -> dict:
        """Checks if HTTP traffic is intercepted by a coffeeshop captive portal."""
        req = urllib.request.Request(CAPTIVE_CHECK_URL, headers={"User-Agent": USER_AGENT})
        try:
            with self.opener.open(req, timeout=5) as resp:
                final_url = resp.geturl()
                content = resp.read().decode("utf-8", errors="ignore")

                is_success = "Success" in content and "hotspot-detect.html" in final_url
                if is_success:
                    return {"is_captive": False, "url": final_url}

                logger.info(f"🚨 Captive portal detected! Redirected to: {final_url}")
                return {
                    "is_captive": True,
                    "url": final_url,
                    "html": content
                }
        except urllib.error.HTTPError as e:
            logger.info(f"Captive portal HTTP {e.code} redirect: {e.url}")
            return {"is_captive": True, "url": e.url, "html": ""}
        except Exception as e:
            return {"is_captive": False, "error": str(e)}

    def solve_captive_portal(self, portal_info: dict) -> bool:
        """Attempts to auto-agree/submit coffeeshop splash page form via actuator gateway (L2)."""
        html = portal_info.get("html", "")
        base_url = portal_info.get("url", "")
        if not html or not base_url:
            return False

        logger.info(f"⚡ Mencoba tembus Captive Portal di: {base_url}...")

        # Find form action
        form_match = re.search(r'<form\s+[^>]*action=["\']([^"\']*)["\']', html, re.IGNORECASE)
        action = form_match.group(1) if form_match else ""
        submit_url = urljoin(base_url, action) if action else base_url

        # Charter v2 (0.5b): Strict same-origin POST guard
        submit_origin = urlparse(submit_url).netloc
        base_origin = urlparse(base_url).netloc
        if submit_origin != base_origin:
            logger.warning(f"Cross-origin captive portal submission blocked: {submit_origin} != {base_origin}")
            return False

        # Harvest input fields (including hidden tokens)
        inputs = re.findall(r'<input\s+[^>]*name=["\']([^"\']+)["\'](?:\s+[^>]*value=["\']([^"\']*)["\'])?', html, re.IGNORECASE)
        payload = {}
        for name, val in inputs:
            payload[name] = val or "1"

        # Common agreement fields in Indonesian coffeeshop Wi-Fis
        payload.update({
            "accept": "true",
            "agree": "1",
            "terms": "1",
            "submit": "Connect",
            "login": "Login",
            "continue": "Lanjut",
            "connect": "Hubungkan"
        })

        def _do_submit():
            encoded_data = urllib.parse.urlencode(payload).encode("utf-8")
            post_req = urllib.request.Request(
                submit_url,
                data=encoded_data,
                headers={
                    "User-Agent": USER_AGENT,
                    "Referer": base_url,
                    "Content-Type": "application/x-www-form-urlencoded"
                }
            )
            with self.opener.open(post_req, timeout=6) as post_resp:
                logger.info(f"Form submitted to {submit_url}. Status: {post_resp.status}")

            time.sleep(2)
            # Re-test captive status
            retest = self.check_captive_portal()
            if not retest.get("is_captive", True):
                return True
            raise RuntimeError("Captive portal retest still reports captive")

        try:
            res = actuate(
                name="wifi_solve_captive_portal",
                tier="L2",
                fn=_do_submit,
                params={"submit_url": submit_url},
                entity="aggressive_wifi",
                reason=f"Coffeeshop captive portal at {urlparse(base_url).netloc}",
                reversible=False
            )
            if res.get("success"):
                logger.info("🎉 CAPTIVE PORTAL BERHASIL DITEMBUS!")
                log_decision(
                    domain="Aggressive Wi-Fi",
                    trigger_event=f"Coffeeshop captive portal at {urlparse(base_url).netloc}",
                    decision_taken="Auto-submitted terms & login form via actuator",
                    outcome="Internet unlocked without human intervention"
                )
                return True
        except ActuatorError as ae:
            logger.warning(f"Actuator blocked captive portal submit: {ae}")
        except Exception as e:
            logger.warning(f"Captive portal auto-submit failed: {e}")

        return False

    def failover_to_hotspot(self) -> bool:
        """Keras-kerasan paksa sambung ke Hotspot HP saat Wi-Fi luar mati via actuator gateway (L2)."""
        logger.info(f"📡 Mencoba paksa failover ke Hotspot: '{PERSONAL_HOTSPOT_SSID}'...")

        def _do_failover():
            # 1. First attempt: switch airport network to personal hotspot
            try:
                cmd = ["networksetup", "-setairportnetwork", self.interface, PERSONAL_HOTSPOT_SSID]
                if PERSONAL_HOTSPOT_PASS:
                    cmd.append(PERSONAL_HOTSPOT_PASS)
                
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if res.returncode == 0:
                    time.sleep(3)
                    if self.has_internet():
                        return "connected_directly"
            except Exception as e:
                logger.debug(f"Direct hotspot connection attempt: {e}")

            # 2. Second attempt: trigger ADB to enable hotspot on POCO M3
            try:
                adb_test = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=3)
                if "device" in adb_test.stdout:
                    logger.info("⚡ Memerintahkan HP via ADB untuk bersiap tethering...")
                    subprocess.run(["adb", "shell", "svc", "wifi", "disable"], timeout=3)
                    subprocess.run(["adb", "shell", "svc", "data", "enable"], timeout=3)
            except Exception:
                pass

            raise RuntimeError("Hotspot failover could not restore connection")

        try:
            res = actuate(
                name="wifi_hotspot_failover",
                tier="L2",
                fn=_do_failover,
                params={"ssid": PERSONAL_HOTSPOT_SSID},
                entity="aggressive_wifi",
                reason="Zero-internet on external Wi-Fi",
                reversible=False
            )
            if res.get("success"):
                logger.info(f"✅ Berhasil tersambung ke Hotspot '{PERSONAL_HOTSPOT_SSID}'!")
                log_decision("Aggressive Wi-Fi", "Zero-internet on external Wi-Fi", f"Auto-connected to hotspot {PERSONAL_HOTSPOT_SSID} via actuator", "Internet restored")
                return True
        except ActuatorError as ae:
            logger.warning(f"Actuator blocked hotspot failover: {ae}")
        except Exception as e:
            logger.debug(f"Hotspot failover attempt: {e}")

        return False

    def run_aggressive_cycle(self) -> dict:
        """Autonomic reflex cycle for total internet continuity."""
        actions_taken = []

        # Step 1: Do we have internet?
        if self.has_internet():
            # Still check if there is an unfulfilled captive portal
            portal = self.check_captive_portal()
            if portal.get("is_captive"):
                if self.solve_captive_portal(portal):
                    actions_taken.append("Solved Captive Portal")
            return {"status": "ONLINE", "actions": actions_taken}

        # Step 2: No internet detected! Check captive portal first
        logger.warning("⚠️ Internet terputus! Memulai protokol agresif Zura...")
        portal = self.check_captive_portal()
        if portal.get("is_captive"):
            if self.solve_captive_portal(portal):
                actions_taken.append("Solved Captive Portal")
                return {"status": "RESTORED_VIA_PORTAL", "actions": actions_taken}

        # Step 3: Wi-Fi fails completely -> Force failover to Personal Hotspot
        if self.failover_to_hotspot():
            actions_taken.append("Failover to Personal Hotspot")
            return {"status": "RESTORED_VIA_HOTSPOT", "actions": actions_taken}

        return {"status": "OFFLINE", "actions": actions_taken}


# Global instance
aggressive_wifi = AggressiveWifiSentinel()


if __name__ == "__main__":
    print("Testing Aggressive Wi-Fi Sentinel...")
    res = aggressive_wifi.run_aggressive_cycle()
    print("Result:", res)
