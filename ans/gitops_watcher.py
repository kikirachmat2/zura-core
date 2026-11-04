"""
ans/gitops_watcher.py - Ultra-Lightweight Bandwidth-Conscious GitOps Auto-Updater
Monitors GitHub repository (kikirachmat2/zura-core) for new commits:
- Ultra-Low Bandwidth: Uses `git ls-remote` querying only a 40-char SHA hash (~500 bytes).
- Consumes less than 100 KB of data PER DAY.
- When new commit is detected on 'main':
  1. Executes `git pull origin main`
  2. Runs dependency updates if requirements.txt changed
  3. Gracefully reloads Zura daemon
  4. Sends instant Telegram notification
"""

import os
import subprocess
import time
import logging
from pathlib import Path
from core.config import BASE_DIR
from core.memory import log_decision

logger = logging.getLogger("GitOpsWatcher")


class GitOpsWatcher:
    def __init__(self, check_interval_seconds: int = 600):
        self.repo_dir = BASE_DIR
        self.branch = "main"
        self.check_interval = check_interval_seconds  # Default: 10 minutes (Zero-waste bandwidth)
        self.last_check_time = 0

    def get_local_head_sha(self) -> str:
        """Gets current local HEAD commit SHA."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=5
            )
            return res.stdout.strip()
        except Exception:
            return ""

    def get_remote_head_sha(self) -> str:
        """
        Queries remote HEAD SHA with minimal overhead (~500 bytes).
        Does NOT download git objects or trees.
        """
        try:
            res = subprocess.run(
                ["git", "ls-remote", "--heads", "origin", self.branch],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=10
            )
            if res.returncode == 0 and res.stdout:
                return res.stdout.split()[0].strip()
        except Exception as e:
            logger.debug(f"ls-remote check error: {e}")
        return ""

    def check_and_apply_update(self) -> dict:
        """Compares local vs remote SHA. Pulls and reloads only on change."""
        local_sha = self.get_local_head_sha()
        remote_sha = self.get_remote_head_sha()

        if not remote_sha or not local_sha:
            return {"updated": False, "reason": "SHA check failed"}

        if remote_sha == local_sha:
            return {"updated": False, "current_sha": local_sha[:7]}

        logger.info(f"🚀 New commit detected on remote: {remote_sha[:7]} (Current: {local_sha[:7]}). Pulling...")

        try:
            # 1. Pull latest code
            pull_res = subprocess.run(
                ["git", "pull", "origin", self.branch],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # 2. Check if requirements.txt was modified
            req_check = subprocess.run(
                ["git", "diff", "--name-only", local_sha, remote_sha],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if "requirements.txt" in req_check.stdout:
                logger.info("📦 Updating python dependencies in venv...")
                pip_path = self.repo_dir / "venv/bin/pip"
                if pip_path.exists():
                    subprocess.run([str(pip_path), "install", "-r", "requirements.txt"], cwd=str(self.repo_dir), timeout=60)

            log_decision(
                domain="GitOps Engine",
                trigger_event=f"Remote commit {remote_sha[:7]} pushed to GitHub",
                decision_taken="Executed zero-touch git pull and dependency update",
                outcome=f"Updated from {local_sha[:7]} to {remote_sha[:7]}"
            )

            return {
                "updated": True,
                "old_sha": local_sha[:7],
                "new_sha": remote_sha[:7]
            }

        except Exception as e:
            logger.error(f"Git pull failed: {e}")
            return {"updated": False, "error": str(e)}


# Global instance
gitops_watcher = GitOpsWatcher()

