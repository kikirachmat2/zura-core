"""
ops/fleet_manager.py - Unified Fleet Takeover & Multi-Repo Deployment Orchestrator
Takes over code stewardship of Zura, KisahKomisi (Threads), and KiBot V3.
Handles multi-repo inspection, automated commits, rsync/SSH upload, and service reloads on Server 1.
"""

import os
import sys
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("FleetManager")

# Base Workstation Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_DEV_DIR = PROJECT_ROOT.parent

FLEET_REPOS = {
    "zura": {
        "name": "ZURA Autonomous Personal AI",
        "local_path": PROJECT_ROOT,
        "remote_path": "/home/ubuntu/zura-core",
        "service_type": "systemd",
        "service_name": "zura.service",
        "restart_cmd": "sudo systemctl restart zura.service",
        "status_cmd": "systemctl is-active zura.service",
        "exclude": [
            "venv", "__pycache__", ".git", "*.db", "logs/*.log",
            "temp_voice/*.mp3", ".env", "*.pyc"
        ]
    },
    "threads": {
        "name": "KisahKomisi Threads Bot",
        "local_path": BASE_DEV_DIR / "Kisah Komisi/kisahkomisi-bot",
        "remote_path": "/home/ubuntu/kisahkomisi-bot",
        "service_type": "pm2",
        "service_name": "kisahkomisi-bot",
        "restart_cmd": "pm2 reload kisahkomisi-bot --update-env",
        "status_cmd": "pm2 describe kisahkomisi-bot | grep -q 'online' && echo active || echo inactive",
        "exclude": [
            "node_modules", ".git", "data/*.db", "data/*.sqlite",
            "*.sqlite", "logs/*.log", ".env"
        ]
    },
    "kibot": {
        "name": "KiBot V3 Indodax Trader",
        "local_path": BASE_DEV_DIR / "KiBot",
        "remote_path": "/home/ubuntu/KiBotV3",
        "service_type": "systemd",
        "service_name": "kibot-v3-core.service",
        "restart_cmd": "sudo systemctl restart kibot-v3-core.service",
        "status_cmd": "systemctl is-active kibot-v3-core.service",
        "exclude": [
            "venv", "__pycache__", ".git", "*.db", "*.db-wal", "*.db-shm",
            "logs/*.log", ".env", "*.pyc"
        ]
    }
}

SERVER_USER = os.getenv("SERVER1_USER", "ubuntu")
SERVER_HOST = os.getenv("SERVER1_HOST", "152.69.218.198")
SERVER_KEY = os.getenv("SERVER1_KEY", str(Path.home() / ".ssh/manake_singapore"))


def run_local_cmd(cmd: List[str], cwd: Path) -> Dict[str, Any]:
    """Runs a local shell command and returns stdout/returncode."""
    try:
        res = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=30)
        return {"success": res.returncode == 0, "stdout": res.stdout.strip(), "stderr": res.stderr.strip()}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e)}


def run_remote_cmd(cmd: str) -> Dict[str, Any]:
    """Runs a remote command on Server 1 via SSH."""
    ssh_cmd = [
        "ssh", "-i", SERVER_KEY,
        "-o", "StrictHostKeyChecking=no",
        f"{SERVER_USER}@{SERVER_HOST}",
        cmd
    ]
    try:
        res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
        return {"success": res.returncode == 0, "stdout": res.stdout.strip(), "stderr": res.stderr.strip()}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e)}


# =====================================================================
# 1. FLEET STATUS & CODE INSPECTION
# =====================================================================

def get_fleet_git_status() -> Dict[str, Any]:
    """Inspects git status, active branch, and modified files across all 3 repos."""
    statuses = {}
    for bot_id, repo in FLEET_REPOS.items():
        loc = repo["local_path"]
        if not loc.exists():
            statuses[bot_id] = {"error": f"Path {loc} does not exist"}
            continue

        st_res = run_local_cmd(["git", "status", "--porcelain"], loc)
        br_res = run_local_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], loc)
        head_res = run_local_cmd(["git", "rev-parse", "--short", "HEAD"], loc)

        changes = [line for line in st_res["stdout"].splitlines() if line.strip()]
        statuses[bot_id] = {
            "name": repo["name"],
            "path": str(loc),
            "branch": br_res["stdout"],
            "commit": head_res["stdout"],
            "has_changes": len(changes) > 0,
            "modified_files_count": len(changes),
            "changes": changes[:10]
        }
    return statuses


# =====================================================================
# 2. COMMIT CODE
# =====================================================================

def commit_fleet_repo(bot_id: str, message: str) -> Dict[str, Any]:
    """Stages all changes and commits in the targeted repo."""
    if bot_id not in FLEET_REPOS:
        return {"success": False, "error": f"Unknown bot {bot_id}"}

    loc = FLEET_REPOS[bot_id]["local_path"]
    add_res = run_local_cmd(["git", "add", "."], loc)
    if not add_res["success"]:
        return {"success": False, "error": add_res["stderr"]}

    status_res = run_local_cmd(["git", "status", "--porcelain"], loc)
    if not status_res["stdout"]:
        return {"success": True, "message": "Nothing to commit, working tree clean."}

    commit_res = run_local_cmd(["git", "commit", "-m", message], loc)
    return {
        "success": commit_res["success"],
        "stdout": commit_res["stdout"],
        "error": commit_res["stderr"] if not commit_res["success"] else None
    }


# =====================================================================
# 3. UPLOAD & DEPLOY TO SERVER 1
# =====================================================================

def deploy_fleet_repo(bot_id: str) -> Dict[str, Any]:
    """Syncs local code to Server 1 and triggers service restart."""
    if bot_id not in FLEET_REPOS:
        return {"success": False, "error": f"Unknown bot {bot_id}"}

    repo = FLEET_REPOS[bot_id]
    loc = repo["local_path"]
    rem = repo["remote_path"]

    # 1. Prepare rsync exclude arguments
    rsync_cmd = [
        "rsync", "-avz",
        "-e", f"ssh -i {SERVER_KEY} -o StrictHostKeyChecking=no"
    ]
    for exc in repo["exclude"]:
        rsync_cmd.extend(["--exclude", exc])

    # Ensure trailing slash so contents are synced properly
    local_str = str(loc) + "/"
    remote_str = f"{SERVER_USER}@{SERVER_HOST}:{rem}/"
    rsync_cmd.extend([local_str, remote_str])

    logger.info(f"🚀 Syncing {bot_id} to Server 1 ({rem})...")
    sync_res = subprocess.run(rsync_cmd, capture_output=True, text=True, timeout=60)
    if sync_res.returncode != 0:
        return {"success": False, "stage": "rsync", "error": sync_res.stderr}

    # 2. Restart remote service
    restart_res = run_remote_cmd(repo["restart_cmd"])
    if not restart_res["success"]:
        return {"success": False, "stage": "restart", "error": restart_res["stderr"]}

    # 3. Verify status
    status_res = run_remote_cmd(repo["status_cmd"])
    is_active = "active" in status_res["stdout"].lower() or "online" in status_res["stdout"].lower()

    return {
        "success": is_active,
        "bot_id": bot_id,
        "name": repo["name"],
        "remote_path": rem,
        "service_status": "ACTIVE" if is_active else "FAILED",
        "output": restart_res["stdout"]
    }


def sync_and_deploy_all(commit_msg: Optional[str] = None) -> Dict[str, Any]:
    """One-stop autonomous workflow: commit changes in any repo, sync to Server 1, and reload services."""
    results = {}
    default_msg = commit_msg or "chore(fleet): autonomous sync and deploy from workstation"

    for bot_id in FLEET_REPOS:
        # Check if changes exist
        loc = FLEET_REPOS[bot_id]["local_path"]
        st = run_local_cmd(["git", "status", "--porcelain"], loc)
        if st["stdout"]:
            commit_res = commit_fleet_repo(bot_id, default_msg)
            results[f"{bot_id}_commit"] = commit_res

        # Deploy
        deploy_res = deploy_fleet_repo(bot_id)
        results[f"{bot_id}_deploy"] = deploy_res

    return results
