"""
ans/mac_daemon.py - Dedicated macOS Background Sentinel Daemon
Runs natively on MacBook Pro 2020:
- Keeps CPU load & thermals optimal (prevents UI lag / micro-stutters)
- Proactively tames background hogs (mdworker, mediaanalysisd, runaway helpers)
- Silently cleans browser & dev caches (Opera, Chrome, updater, pip, npm)
- Auto-boosts Wi-Fi network & flushes DNS when jitter/lag is detected
"""

import os
import sys
import time
import signal
import logging
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from ans.mac_sentinel import mac_sentinel
from ans.mobile_sentinel import mobile_sentinel
from network.wifi_watchdog import wifi_watchdog
from network.aggressive_wifi import aggressive_wifi
from core.config import LOGS_DIR

LOGS_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOGS_DIR / "mac_sentinel.log"

logger = logging.getLogger("MacDaemon")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(file_handler)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(stream_handler)

is_running = True


def handle_shutdown(signum, frame):
    global is_running
    logger.info("Shutdown signal received. Mac Sentinel stopping cleanly.")
    is_running = False


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


def main():
    # Lower process priority so Sentinel itself NEVER competes with user apps
    try:
        os.nice(10)
    except Exception:
        pass

    logger.info("🛡️ ZURA Mac Sentinel Daemon Active (MacBook Pro 2020 Safeguard)")
    logger.info("Monitoring Thermals, Load Average, Memory Compression & Network...")

    cycle = 0
    while is_running:
        cycle += 1
        try:
            # 1. Run Autonomic Hardware & Memory Care (Every 30s)
            res = mac_sentinel.run_autonomic_cycle()
            t = res["telemetry"]

            if res["tamed_processes"]:
                for p in res["tamed_processes"]:
                    logger.info(f"⚡ {p}")

            if res["cache_freed_mb"] > 0:
                logger.info(f"🧹 Vacuumed {res['cache_freed_mb']} MB disk cache")

            # 2. Network & Aggressive Wi-Fi Sentinel Check (Every 60s)
            if cycle % 2 == 0:
                net_res = wifi_watchdog.auto_heal_network()
                if net_res["actions_taken"]:
                    logger.info(f"📡 Wi-Fi Auto-Healed: {net_res['actions_taken']}")

                # Aggressive connectivity & captive portal unlocker
                aggr_res = aggressive_wifi.run_aggressive_cycle()
                if aggr_res.get("actions"):
                    logger.info(f"🔓 Aggressive Wi-Fi Action: {aggr_res['actions']}")

            # 3. Mobile Device Sentinel (POCO M3) Safeguard (Every 60s)
            if cycle % 2 == 0:
                try:
                    m_tele = mobile_sentinel.read_telemetry()
                    if m_tele.get("connected"):
                        if m_tele.get("thermal_warning"):
                            logger.warning(f"🔥 POCO M3 Battery Overheat: {m_tele['temp_c']}°C >= 40°C! Triggering thermal protection...")
                            prot = mobile_sentinel.execute_thermal_protection()
                            logger.info(f"Mobile thermal protection executed: {prot}")
                        elif m_tele.get("overcharge_warning") and cycle % 10 == 0:
                            logger.info(f"🔋 POCO M3 Battery at {m_tele['level']}% (>=80% optimal ceiling while charging).")
                except Exception as m_err:
                    logger.debug(f"Mobile Sentinel cycle check: {m_err}")

        except Exception as e:
            logger.error(f"Mac Sentinel loop error: {e}")

        time.sleep(30)


if __name__ == "__main__":
    main()
