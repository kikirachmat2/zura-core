"""
ans/mobile_sentinel.py - Zura Autonomous Mobile Device Sentinel (POCO M3)
Per Zura Charter v2:
1. Monitors physical health of mobile fleet: POCO M3 (serial: 40d203460421).
2. Battery Overheat Protection: Alarms and dims screen/kills hogs when temp >= 40°C.
3. Overcharge Limiter: Alerts when battery hits 80% while on AC charger to preserve battery lifespan.
4. Wireless ADB Auto-Failover: Switches to TCP/IP port 5555 so device remains connected when unplugged.
"""

import os
import re
import sys
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

# Ensure standard bin paths are in PATH (needed when running under launchd)
for p in ["/usr/local/bin", "/opt/homebrew/bin"]:
    if p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{p}:{os.environ.get('PATH', '')}"

ADB_BIN = shutil.which("adb") or "/usr/local/bin/adb"

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.memory import log_decision, set_state, get_state
from core.actuator import actuate, ActuatorError

logger = logging.getLogger("MobileSentinel")


class MobileSentinel:
    DEFAULT_POCO_SERIAL = "40d203460421"
    SAFE_MAX_BATTERY_TEMP_C = 40.0
    OPTIMAL_CHARGE_CEILING = 80

    def __init__(self, serial: Optional[str] = None):
        self.serial = serial or os.getenv("POCO_SERIAL", self.DEFAULT_POCO_SERIAL)
        self.device_ip = os.getenv("POCO_IP", "")

    def get_connected_devices(self) -> Dict[str, str]:
        """Runs `adb devices` and maps serial -> status."""
        devices = {}
        try:
            res = subprocess.run([ADB_BIN, "devices"], capture_output=True, text=True, timeout=5)
            for line in res.stdout.splitlines()[1:]:
                parts = line.strip().split()
                if len(parts) >= 2:
                    devices[parts[0]] = parts[1]
        except Exception as e:
            logger.warning("adb devices check failed: %s", e)
        return devices

    def is_device_connected(self) -> bool:
        devs = self.get_connected_devices()
        # Check by serial or IP
        if self.serial in devs and devs[self.serial] == "device":
            return True
        if self.device_ip and f"{self.device_ip}:5555" in devs and devs[f"{self.device_ip}:5555"] == "device":
            return True
        return False

    def discover_device_ip(self) -> Optional[str]:
        """Discovers POCO M3 Wi-Fi IP address via ADB."""
        target = self.serial if self.serial in self.get_connected_devices() else None
        if not target:
            return self.device_ip or None

        try:
            cmd = [ADB_BIN, "-s", target, "shell", "ip", "-f", "inet", "addr", "show", "wlan0"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", res.stdout)
            if match:
                self.device_ip = match.group(1)
                return self.device_ip
        except Exception as e:
            logger.debug("Failed to discover IP via wlan0: %s", e)

        return None

    def enable_wireless_adb(self, port: int = 5555) -> Dict[str, Any]:
        """
        Switches POCO M3 to Wireless TCP/IP mode so it remains reachable
        even when physical USB cable is unplugged.
        """
        ip = self.discover_device_ip()
        target = self.serial if self.serial in self.get_connected_devices() else None

        if not target:
            # If not on USB, attempt to connect to existing IP
            if ip:
                conn_res = subprocess.run([ADB_BIN, "connect", f"{ip}:{port}"], capture_output=True, text=True, timeout=5)
                return {
                    "success": "connected" in conn_res.stdout.lower(),
                    "mode": "wireless_reconnect",
                    "ip": ip,
                    "port": port,
                    "output": conn_res.stdout.strip()
                }
            return {"success": False, "error": "Device not connected via USB or Wi-Fi"}

        try:
            # 1. Enable TCP/IP on device
            subprocess.run([ADB_BIN, "-s", target, "tcpip", str(port)], capture_output=True, text=True, timeout=6)
            import time
            time.sleep(2.0)  # Allow adbd daemon to rebind in TCP mode
            
            # 2. Connect via Wi-Fi if IP is known
            if ip:
                conn = subprocess.run([ADB_BIN, "connect", f"{ip}:{port}"], capture_output=True, text=True, timeout=6)
                is_connected = ("connected" in conn.stdout.lower() or "already connected" in conn.stdout.lower())
                return {
                    "success": is_connected,
                    "mode": "wireless_established",
                    "ip": ip,
                    "port": port,
                    "output": conn.stdout.strip()
                }
            return {
                "success": True,
                "mode": "tcpip_ready_awaiting_ip",
                "port": port
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def read_telemetry(self) -> Dict[str, Any]:
        """
        Parses battery, thermal, and screen state from POCO M3 dumpsys.
        """
        devs = self.get_connected_devices()
        active_target = None
        if self.serial in devs and devs[self.serial] == "device":
            active_target = self.serial
        elif self.device_ip and f"{self.device_ip}:5555" in devs:
            active_target = f"{self.device_ip}:5555"

        if not active_target:
            return {
                "connected": False,
                "status": "DEVICE_OFFLINE",
                "serial": self.serial,
                "timestamp": datetime.now().isoformat()
            }

        telemetry = {
            "connected": True,
            "target": active_target,
            "serial": self.serial,
            "level": 0,
            "temp_c": 0.0,
            "is_charging": False,
            "charge_type": "None",
            "thermal_warning": False,
            "overcharge_warning": False,
            "timestamp": datetime.now().isoformat()
        }

        try:
            # 1. Battery Dump
            res = subprocess.run([ADB_BIN, "-s", active_target, "shell", "dumpsys", "battery"], capture_output=True, text=True, timeout=5)
            for line in res.stdout.splitlines():
                line = line.strip()
                if line.startswith("level:"):
                    telemetry["level"] = int(line.split(":")[1].strip())
                elif line.startswith("temperature:"):
                    # Temperature in tenths of degree Celsius
                    telemetry["temp_c"] = int(line.split(":")[1].strip()) / 10.0
                elif line.startswith("AC powered:") and "true" in line:
                    telemetry["is_charging"] = True
                    telemetry["charge_type"] = "AC"
                elif line.startswith("USB powered:") and "true" in line:
                    telemetry["is_charging"] = True
                    telemetry["charge_type"] = "USB"

            # 2. Thermal threshold check
            if telemetry["temp_c"] >= self.SAFE_MAX_BATTERY_TEMP_C:
                telemetry["thermal_warning"] = True

            # 3. Overcharge ceiling check (Context-Aware: Dynamic 80% vs 100% Field Mode)
            ceiling = self.OPTIMAL_CHARGE_CEILING
            field_mode = get_state("mobile_field_mode", {})
            import time
            if field_mode.get("active") and time.time() < field_mode.get("expires_at", 0):
                ceiling = 100
                telemetry["field_mode_active"] = True
            else:
                telemetry["field_mode_active"] = False

            telemetry["charge_ceiling"] = ceiling
            if telemetry["is_charging"] and telemetry["level"] >= ceiling:
                telemetry["overcharge_warning"] = True

            set_state("poco_telemetry", telemetry)
            return telemetry
        except Exception as e:
            logger.warning("Failed to read POCO telemetry: %s", e)
            return {"connected": False, "error": str(e)}

    def execute_thermal_protection(self) -> Dict[str, Any]:
        """
        Emergency thermal action:
        Dims screen to minimum, kills background CPU hogs, and records alert.
        """
        devs = self.get_connected_devices()
        target = self.serial if self.serial in devs else (f"{self.device_ip}:5555" if f"{self.device_ip}:5555" in devs else None)
        if not target:
            return {"success": False, "error": "Target device not reachable"}

        actions = []
        try:
            # Dim screen
            subprocess.run([ADB_BIN, "-s", target, "shell", "settings", "put", "system", "screen_brightness", "10"], capture_output=True, timeout=4)
            actions.append("screen_dimmed_to_10")
            
            # Kill background hogs
            subprocess.run([ADB_BIN, "-s", target, "shell", "am", "kill-all"], capture_output=True, timeout=4)
            actions.append("background_apps_killed")

            log_decision(
                domain="mobile_sentinel",
                trigger_event="Battery temperature exceeded 40.0°C safety ceiling",
                decision_taken="Executed emergency thermal throttling on POCO M3",
                outcome="SUCCESS"
            )
            return {"success": True, "actions": actions}
        except Exception as e:
            return {"success": False, "error": str(e)}


    def set_field_work_mode(self, enabled: bool = True, duration_hours: float = 12.0) -> Dict[str, Any]:
        """
        Context-Aware Charging Mode:
        Overrides the 80% battery conservation ceiling to 100% full capacity
        when Bos Kiki is traveling, attending film production shoots, or requires maximum battery utility.
        """
        import time
        if enabled:
            expires_at = time.time() + (duration_hours * 3600.0)
            state = {
                "active": True,
                "duration_hours": duration_hours,
                "expires_at": expires_at,
                "activated_at": time.time()
            }
            set_state("mobile_field_mode", state)
            log_decision(
                domain="mobile_sentinel",
                trigger_event="Field work mode requested",
                decision_taken=f"Raised POCO M3 charge ceiling to 100% for {duration_hours}h",
                outcome="SUCCESS"
            )
            return {"active": True, "charge_ceiling": 100, "duration_hours": duration_hours}
        else:
            set_state("mobile_field_mode", {"active": False})
            log_decision(
                domain="mobile_sentinel",
                trigger_event="Field work mode deactivated",
                decision_taken="Restored POCO M3 charge ceiling to 80% conservation mode",
                outcome="SUCCESS"
            )
            return {"active": False, "charge_ceiling": self.OPTIMAL_CHARGE_CEILING}


# Global instance
mobile_sentinel = MobileSentinel()
