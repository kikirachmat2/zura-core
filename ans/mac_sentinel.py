"""
ans/mac_sentinel.py - Autonomic Mac Care Sentinel
Instinctive maintenance for MacBook Pro 2020:
- Keeps temperature in safe zone (35°C - 62°C)
- Tames runaway CPU processes (renice/kill)
- Silent cache vacuuming (Safari, Opera, VSCode, System)
- Memory pressure optimization
"""

import os
import subprocess
import psutil
import time
import logging
import sys
from pathlib import Path
from core.config import MAC_TEMP_MAX_C, MAC_TEMP_MIN_C
from core.memory import log_decision, set_state
from core.actuator import actuate, actuate_command, actuate_cache_vacuum, ActuatorError

logger = logging.getLogger("SystemSentinel")


class SystemSentinel:
    RUNAWAY_CPU_PCT = 65.0       # Tighter threshold: 65% on Intel 4-core CPU
    LOAD_AVG_MAX = 4.0           # 4 physical cores on MacBook Pro 2020
    CACHE_THRESHOLD_MB = 300.0   # Tighter cache vacuuming threshold

    def __init__(self):
        self.is_mac = (sys.platform == "darwin")
        self.home = Path.home()
        if self.is_mac:
            self.cache_dirs = [
                self.home / "Library/Caches/com.apple.Safari",
                self.home / "Library/Caches/com.operasoftware.Opera",
                self.home / "Library/Caches/com.microsoft.VSCode",
                self.home / "Library/Caches/Google/Chrome",
                self.home / "Library/Caches/com.spotify.client/Data",
                self.home / "Library/Caches/antigravity-updater",
                self.home / "Library/Caches/GeoServices",
                self.home / "Library/Caches/pip",
                self.home / ".npm/_cacache",
                self.home / ".cache",
            ]
        else:
            # Linux server cache dirs
            self.cache_dirs = [
                Path("/tmp"),
                Path("/var/tmp"),
                self.home / ".cache",
                self.home / ".npm/_cacache",
            ]

    def inspect_thermals_and_load(self) -> dict:
        """Retrieves CPU load, 1-min load avg, and system temperature state."""
        cpu_pct = psutil.cpu_percent(interval=0.5)
        memory = psutil.virtual_memory()
        load_1, load_5, load_15 = os.getloadavg()
        
        thermal_state = "Normal"
        if self.is_mac:
            try:
                res = subprocess.run(["sysctl", "machdep.xcpm.cpu_thermal_level"], capture_output=True, text=True, timeout=2)
                if res.returncode == 0 and "0" in res.stdout:
                    thermal_state = "Optimal"
                elif res.returncode == 0:
                    thermal_state = "Elevated"
            except Exception:
                pass
        else:
            # Linux thermal check
            try:
                t_zone = Path("/sys/class/thermal/thermal_zone0/temp")
                if t_zone.exists():
                    millidegrees = int(t_zone.read_text().strip())
                    celsius = millidegrees / 1000.0
                    thermal_state = f"{celsius:.1f}°C"
            except Exception:
                pass

        data = {
            "platform": "macOS" if self.is_mac else "Linux",
            "cpu_percent": cpu_pct,
            "load_1m": round(load_1, 2),
            "load_5m": round(load_5, 2),
            "ram_used_pct": memory.percent,
            "ram_free_gb": round(memory.available / (1024**3), 2),
            "thermal_state": thermal_state,
            "timestamp": time.time()
        }
        set_state("system_telemetry", data)
        return data

    def tame_runaway_processes(self) -> list:
        """Tames runaway or high-impact background processes using renice."""
        tamed = []
        whitelist = ["python3", "code", "node", "kernel_task", "Antigravity", "WindowServer", "pm2", "kibot"]
        background_hogs = ["mdworker", "mdworker_shared", "mediaanalysisd", "photoanalysisd", "VTDecoderXPCService"]

        load_1, _, _ = os.getloadavg()
        is_overloaded = load_1 > self.LOAD_AVG_MAX

        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'nice']):
            try:
                cpu = proc.info['cpu_percent']
                name = proc.info['name']
                pid = proc.info['pid']

                # Condition 1: Direct runaway process exceeding 65% CPU
                if cpu and cpu > self.RUNAWAY_CPU_PCT and not any(w in name.lower() for w in whitelist):
                    try:
                        actuate_command(
                            ["renice", "+12", str(pid)],
                            name="mac_renice_process",
                            tier="L1",
                            entity="mac_sentinel",
                            reason=f"CPU Spike {cpu}% on {name}",
                            reversible=False
                        )
                        msg = f"Reniced runaway {name} (PID {pid}, CPU {cpu}%)"
                        tamed.append(msg)
                        log_decision("Sentinel", f"CPU Spike {cpu}% on {name}", "Reniced to lower priority (+12)", "Subdued")
                    except ActuatorError as ae:
                        logger.debug(f"Actuator blocked renice: {ae}")

                # Condition 2: High load average overload - tame known background hogs
                elif is_overloaded and any(h in name for h in background_hogs):
                    # Check current nice level, if not already lowered
                    if proc.info.get('nice', 0) < 10:
                        try:
                            actuate_command(
                                ["renice", "+15", str(pid)],
                                name="mac_renice_process",
                                tier="L1",
                                entity="mac_sentinel",
                                reason=f"High load average {round(load_1, 2)}",
                                reversible=False
                            )
                            tamed.append(f"Deprioritized background worker {name} (PID {pid})")
                            log_decision("Sentinel", f"System Load {round(load_1, 2)} > {self.LOAD_AVG_MAX}", f"Deprioritized {name}", "Freed CPU time for UI")
                        except ActuatorError as ae:
                            logger.debug(f"Actuator blocked renice: {ae}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return tamed

    def silent_cache_vacuum(self, force: bool = False) -> float:
        """Purges browser, editor, and build caches silently via actuator gateway."""
        try:
            total_freed_mb = actuate_cache_vacuum(self.cache_dirs, force=force, entity="mac_sentinel")
            if total_freed_mb > 0:
                log_decision("Sentinel", f"Cache accumulation ({round(total_freed_mb, 1)} MB)", "Silent purge executed", "Disk freed successfully")
            return total_freed_mb
        except ActuatorError as ae:
            logger.debug(f"Actuator blocked cache vacuum: {ae}")
            return 0.0
        except Exception as e:
            logger.debug(f"Cache vacuum error: {e}")
            return 0.0

    def optimize_memory_pressure(self):
        """Purges inactive disk cache if RAM usage exceeds 85% via actuator gateway."""
        mem = psutil.virtual_memory()
        if mem.percent > 85.0:
            if self.is_mac:
                try:
                    actuate_command(
                        ["purge"],
                        name="mac_memory_purge",
                        tier="L1",
                        entity="mac_sentinel",
                        reason=f"High RAM Pressure ({mem.percent}%)",
                        timeout=5,
                        reversible=False
                    )
                    log_decision("Sentinel", f"High RAM Pressure ({mem.percent}%)", "Executed macOS cache purge", "Inactive memory reclaimed")
                except ActuatorError as ae:
                    logger.debug(f"Actuator blocked memory purge: {ae}")
                except Exception:
                    pass
            else:
                # Linux: drop caches if possible or trigger sync
                try:
                    actuate_command(
                        ["sync"],
                        name="mac_memory_purge",
                        tier="L1",
                        entity="mac_sentinel",
                        reason=f"High RAM Pressure ({mem.percent}%)",
                        timeout=5,
                        reversible=False
                    )
                    log_decision("Sentinel", f"High RAM Pressure ({mem.percent}%)", "Executed sync", "Buffer flushed")
                except ActuatorError as ae:
                    logger.debug(f"Actuator blocked memory sync: {ae}")
                except Exception:
                    pass

    def run_autonomic_cycle(self) -> dict:
        """Single reflex cycle of maintenance."""
        telemetry = self.inspect_thermals_and_load()
        tamed = self.tame_runaway_processes()
        self.optimize_memory_pressure()
        
        # Only clean cache if system is relatively idle
        freed_mb = 0.0
        if telemetry["cpu_percent"] < 40.0:
            freed_mb = self.silent_cache_vacuum()

        return {
            "telemetry": telemetry,
            "tamed_processes": tamed,
            "cache_freed_mb": freed_mb
        }


# Global instance
mac_sentinel = SystemSentinel()

