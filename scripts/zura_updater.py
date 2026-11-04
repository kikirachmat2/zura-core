#!/usr/bin/env python3
"""
scripts/zura_updater.py - Decoupled GitOps Service Restart & Heartbeat Verifier
Runs independently under zura-updater.service (or out-of-tree safe copy)
outside the zura.service cgroup so it survives zura.service restarts.

Workflow:
1. Reads .git/pending_update.json (chmod 600, no secrets stored).
2. Reads TELEGRAM_BOT_TOKEN securely from .env.
3. Records initial NRestarts from systemd.
4. Executes: sudo systemctl restart zura.service
5. Verifies heartbeat for 45-60 seconds:
   - Fails if NRestarts increases (service is crash-looping/flapping).
   - Fails if ActiveState enters failed/dead.
   - Succeeds only when SQLite 'last_ans_heartbeat' timestamp > restart_time.
6. On success: removes pending_update.json and dispatches Telegram notification.
7. On failure: performs hard-rollback (git reset --hard pre_pull_sha),
   restores pip dependencies, restarts old version, cleans marker, and alerts Master.
"""

import os
import sys
import json
import time
import sqlite3
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MARKER_PATH = BASE_DIR / ".git" / "pending_update.json"
ENV_PATH = BASE_DIR / ".env"


def load_bot_token_from_env() -> str:
    """Reads TELEGRAM_BOT_TOKEN directly from .env without exposing in marker."""
    if not ENV_PATH.exists():
        return ""
    try:
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                val = line.split("=", 1)[1].strip()
                return val.strip('"').strip("'")
    except Exception:
        pass
    return ""


def send_telegram(token: str, chat_id: int, text: str):
    """Sends Telegram message directly via HTTP without third-party libraries."""
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            pass
    except Exception as e:
        print(f"[ZuraUpdater] Telegram alert error: {e}", file=sys.stderr)


def get_db_heartbeat(db_path: Path) -> float:
    """Reads latest heartbeat timestamp from system_state table in SQLite."""
    if not db_path.exists():
        return 0.0
    try:
        conn = sqlite3.connect(str(db_path), timeout=3)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM system_state WHERE key = 'last_ans_heartbeat'")
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return float(row[0])
    except Exception:
        pass
    return 0.0


def get_systemd_property(service_name: str, prop: str) -> str:
    """Retrieves systemctl show property value."""
    try:
        res = subprocess.run(
            ["systemctl", "show", service_name, f"--property={prop}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if res.returncode == 0 and "=" in res.stdout:
            return res.stdout.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def main():
    if not MARKER_PATH.exists():
        print("[ZuraUpdater] No pending update marker found. Exiting.")
        return 0

    try:
        marker = json.loads(MARKER_PATH.read_text())
    except Exception as e:
        print(f"[ZuraUpdater] Failed to read marker: {e}", file=sys.stderr)
        return 1

    pre_pull_sha = marker.get("pre_pull_sha", "")
    target_sha = marker.get("target_sha", "")
    chat_id = marker.get("chat_id", 0)
    db_path = Path(marker.get("db_path", str(BASE_DIR / "data" / "zura.db")))
    pre_freeze_path = marker.get("pre_freeze_path")

    bot_token = load_bot_token_from_env()
    is_linux = sys.platform.startswith("linux")
    restart_time = time.time()

    if is_linux:
        # 1. Record initial restart counter to detect crash-looping
        initial_restarts_str = get_systemd_property("zura.service", "NRestarts")
        initial_restarts = int(initial_restarts_str) if initial_restarts_str.isdigit() else 0

        print(f"[ZuraUpdater] Restarting zura.service (initial restarts={initial_restarts})...")
        restart_res = subprocess.run(["sudo", "systemctl", "restart", "zura.service"], capture_output=True, text=True, timeout=15)
        if restart_res.returncode != 0:
            err = restart_res.stderr.strip() or "systemctl restart failed"
            return handle_failure(pre_pull_sha, target_sha, bot_token, chat_id, pre_freeze_path, f"Restart command error: {err}")

        # 2. Monitor heartbeat for up to 50 seconds
        print("[ZuraUpdater] Verifying heartbeat and NRestarts for 50s...")
        heartbeat_verified = False
        for elapsed in range(1, 51):
            time.sleep(1)

            # Flapping detection
            restarts_str = get_systemd_property("zura.service", "NRestarts")
            restarts = int(restarts_str) if restarts_str.isdigit() else 0
            if restarts > initial_restarts:
                return handle_failure(pre_pull_sha, target_sha, bot_token, chat_id, pre_freeze_path, "Service is flapping (NRestarts increased)")

            # Dead state detection
            state = get_systemd_property("zura.service", "ActiveState")
            substate = get_systemd_property("zura.service", "SubState")
            if state in ["failed", "dead"]:
                return handle_failure(pre_pull_sha, target_sha, bot_token, chat_id, pre_freeze_path, f"Service entered {state} state ({substate})")

            # Check DB heartbeat
            hb = get_db_heartbeat(db_path)
            if hb > restart_time:
                heartbeat_verified = True
                print(f"[ZuraUpdater] Heartbeat verified after {elapsed}s (hb={hb} > restart_time={restart_time})")
                break

        if not heartbeat_verified:
            return handle_failure(pre_pull_sha, target_sha, bot_token, chat_id, pre_freeze_path, "Heartbeat timeout (no fresh DB heartbeat within 50s)")

    # Success cleanup
    MARKER_PATH.unlink(missing_ok=True)
    success_msg = (
        f"✅ <b>GITOPS DEPLOY SUKSES (VERIFIED):</b>\n\n"
        f"• <b>Commit Baru:</b> <code>{target_sha[:7]}</code>\n"
        f"• <b>Service:</b> zura.service aktif & stabil.\n"
        f"• <b>Heartbeat:</b> Terverifikasi responsif."
    )
    send_telegram(bot_token, chat_id, success_msg)
    print(f"[ZuraUpdater] Update {target_sha[:7]} successfully deployed and verified.")
    return 0


def handle_failure(pre_pull_sha: str, target_sha: str, bot_token: str, chat_id: int, pre_freeze_path: str, reason: str) -> int:
    """Executes emergency hard-rollback and restores old service version."""
    print(f"[ZuraUpdater] 🚨 DEPLOYMENT FAILED: {reason}. Triggering emergency rollback to {pre_pull_sha[:7]}...", file=sys.stderr)

    # 1. Reset git tree to pre-pull SHA
    subprocess.run(["git", "reset", "--hard", pre_pull_sha], cwd=str(BASE_DIR), capture_output=True, timeout=15)
    subprocess.run(["git", "clean", "-fd"], cwd=str(BASE_DIR), capture_output=True, timeout=15)

    # 2. Restore pip dependencies if saved
    if pre_freeze_path and os.path.exists(pre_freeze_path):
        pip_path = BASE_DIR / "venv" / "bin" / "pip"
        if pip_path.exists():
            subprocess.run([str(pip_path), "install", "-r", pre_freeze_path], cwd=str(BASE_DIR), capture_output=True, timeout=90)
            try:
                os.unlink(pre_freeze_path)
            except Exception:
                pass

    # 3. Restart previous working service
    if sys.platform.startswith("linux"):
        subprocess.run(["sudo", "systemctl", "restart", "zura.service"], capture_output=True, timeout=15)

    # 4. Clean marker
    MARKER_PATH.unlink(missing_ok=True)

    # 5. Dispatch Telegram alert
    alert_msg = (
        f"🚨 <b>GITOPS DEPLOY GAGAL (AUTO-ROLLBACK DIEKSEKUSI):</b>\n\n"
        f"• <b>Target Commit:</b> <code>{target_sha[:7]}</code> (Gagal)\n"
        f"• <b>Penyebab:</b> <code>{reason}</code>\n"
        f"• <b>Status:</b> Otomatis di-rollback ke commit <code>{pre_pull_sha[:7]}</code> dan service versi lama di-restart."
    )
    send_telegram(bot_token, chat_id, alert_msg)
    return 1


if __name__ == "__main__":
    sys.exit(main())
