"""
ans/gitops_watcher.py - Hardened GitOps Guardian (v0.1b)
Complies with Zura Charter v2:
- Zero auto-pull: Autonomous code application is strictly prohibited (L3 Guardrail).
- Detection only: Checks remote commit SHA using ultra-low-bandwidth `git ls-remote`.
- Rich Audit Alert: Details commit message, author, diff stat, and sensitive file/sudo warnings.
- Human Approval: Pulls ONLY upon explicit user approval tied to target SHA.
- Strict Validations:
  * Rejects if git status --porcelain is dirty.
  * Rejects if target SHA != 40-char hex.
  * Rejects if target SHA is no longer remote HEAD (anti-staleness).
  * Rejects if target SHA is not an ancestor of origin/<branch>.
  * Anti-double-tap locking mechanism.
- Pre-flight Sanity: Runs py_compile on all python files and import tests before accepting.
- Dependency Rollback: Backs up pip freeze before install and restores upon rollback.
- Service Verification: Restarts zura.service (on Linux) and verifies heartbeat, rolling back if dead.
- Automated Hard-Rollback: Instantly reverts working tree to exact pre-pull SHA.
"""

import os
import sys
import re
import time
import threading
import subprocess
import logging
import py_compile
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
from core.config import BASE_DIR, GITOPS_BRANCH
from core.memory import log_decision

logger = logging.getLogger("GitOpsWatcher")

SHA_40_REGEX = re.compile(r"^[0-9a-f]{40}$")


class GitOpsWatcher:
    def __init__(self, check_interval_seconds: int = 600, repo_dir: Optional[Path] = None, branch: Optional[str] = None):
        self.repo_dir = Path(repo_dir) if repo_dir else BASE_DIR
        self.branch = branch or GITOPS_BRANCH
        self.check_interval = check_interval_seconds
        self.last_check_time = 0
        self._lock = threading.Lock()

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
        except Exception as e:
            logger.debug(f"rev-parse HEAD error: {e}")
            return ""

    def get_remote_head_sha_info(self) -> Tuple[str, Optional[str]]:
        """
        Queries remote HEAD SHA with minimal bandwidth (~500 bytes).
        Does NOT download git objects or trees. Returns (sha, error_message).
        """
        try:
            res = subprocess.run(
                ["git", "ls-remote", "--heads", "origin", self.branch],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=15
            )
            if res.returncode == 0 and res.stdout:
                return res.stdout.split()[0].strip(), None
            err_msg = res.stderr.strip() or f"ls-remote exited with code {res.returncode}"
            logger.error(f"ls-remote check error: {err_msg}")
            return "", err_msg
        except Exception as e:
            logger.error(f"ls-remote exception: {e}")
            return "", str(e)

    def get_remote_head_sha(self) -> str:
        """Convenience method returning SHA or empty string on error."""
        sha, _ = self.get_remote_head_sha_info()
        return sha

    def check_for_updates(self) -> Dict[str, Any]:
        """
        Pure telemetry check: compares local vs remote SHA.
        NEVER pulls code autonomously. Returns rich metadata and security warnings.
        """
        local_sha = self.get_local_head_sha()
        remote_sha, remote_err = self.get_remote_head_sha_info()

        if remote_err:
            return {
                "update_available": False,
                "error": remote_err,
                "failed": True,
                "reason": f"Remote query failed: {remote_err}"
            }

        if not remote_sha or not local_sha:
            return {"update_available": False, "reason": "SHA check failed"}

        if remote_sha == local_sha:
            return {"update_available": False, "current_sha": local_sha[:7]}

        # Fetch remote metadata for rich auditing
        fetch_res = subprocess.run(
            ["git", "fetch", "origin", self.branch],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=20
        )
        if fetch_res.returncode != 0:
            return {
                "update_available": True,
                "local_sha": local_sha[:7],
                "remote_sha": remote_sha[:7],
                "full_remote_sha": remote_sha,
                "branch": self.branch,
                "commit_message": "Metadata fetch failed",
                "author": "Unknown",
                "diff_stat": "N/A",
                "warnings": []
            }

        # 1. Commit message & Author
        log_res = subprocess.run(
            ["git", "log", "-1", "--format=%s|||%an <%ae>", remote_sha],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=5
        )
        commit_msg = "No message"
        author = "Unknown"
        if log_res.returncode == 0 and "|||" in log_res.stdout:
            parts = log_res.stdout.strip().split("|||", 1)
            commit_msg = parts[0].strip()
            author = parts[1].strip()

        # 2. Diff stat
        stat_res = subprocess.run(
            ["git", "diff", "--stat", local_sha, remote_sha],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=5
        )
        diff_stat = stat_res.stdout.strip() if stat_res.returncode == 0 else ""

        # 3. Changed files & sensitive inspections
        files_res = subprocess.run(
            ["git", "diff", "--name-only", local_sha, remote_sha],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=5
        )
        changed_files = files_res.stdout.splitlines() if files_res.returncode == 0 else []

        warnings: List[str] = []
        if "requirements.txt" in changed_files:
            warnings.append("⚠️ requirements.txt (Dependencies berubah)")
        if "ans/gitops_watcher.py" in changed_files:
            warnings.append("⚠️ ans/gitops_watcher.py (Core GitOps logic berubah)")
        if any(f.startswith("scripts/") for f in changed_files):
            warnings.append("⚠️ scripts/ (Skrip operasional / deploy berubah)")

        # 4. Check for newly introduced sudo or subprocess calls in diff
        diff_text_res = subprocess.run(
            ["git", "diff", local_sha, remote_sha],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=10
        )
        if diff_text_res.returncode == 0:
            diff_lines = diff_text_res.stdout.splitlines()
            has_new_subprocess = any(line.startswith("+") and not line.startswith("+++") and "subprocess" in line for line in diff_lines)
            has_new_sudo = any(line.startswith("+") and not line.startswith("+++") and "sudo" in line for line in diff_lines)
            if has_new_sudo:
                warnings.append("🚨 Diff menambahkan pemanggilan sudo baru!")
            if has_new_subprocess:
                warnings.append("🚨 Diff menambahkan pemanggilan subprocess baru!")

        return {
            "update_available": True,
            "local_sha": local_sha[:7],
            "remote_sha": remote_sha[:7],
            "full_remote_sha": remote_sha,
            "branch": self.branch,
            "commit_message": commit_msg,
            "author": author,
            "diff_stat": diff_stat,
            "warnings": warnings
        }

    def validate_code_syntax(self) -> Tuple[bool, str]:
        """
        Compiles all Python files in the repository to bytecode.
        Detects syntax errors before new code runs in production.
        """
        excluded_dirs = {".git", "venv", ".venv", "__pycache__", ".pytest_cache", "data"}
        
        for root, dirs, files in os.walk(self.repo_dir):
            dirs[:] = [d for d in dirs if d not in excluded_dirs and not d.startswith(".")]
            for file in files:
                if file.endswith(".py"):
                    full_path = Path(root) / file
                    try:
                        py_compile.compile(str(full_path), doraise=True)
                    except py_compile.PyCompileError as e:
                        return False, f"Syntax error in {full_path.relative_to(self.repo_dir)}: {e.msg}"
                    except Exception as e:
                        return False, f"Compile error in {full_path.relative_to(self.repo_dir)}: {str(e)}"

        return True, "All python files compiled successfully"

    def apply_update(self, target_sha: str) -> Dict[str, Any]:
        """
        Executes L3-authorized update strictly tied to the verified target_sha.
        Includes sanity validation, pip freeze backup/restore, systemd verification,
        and automated hard-rollback on failure.
        """
        # Anti double-tap lock
        if not self._lock.acquire(blocking=False):
            return {"success": False, "stage": "lock", "error": "An update operation is already in progress"}

        try:
            return self._apply_update_internal(target_sha)
        finally:
            self._lock.release()

    def _apply_update_internal(self, target_sha: str) -> Dict[str, Any]:
        target_sha = target_sha.strip().lower()

        # 1. Regex validation: Must be exactly 40 lowercase hex characters
        if not SHA_40_REGEX.match(target_sha):
            return {
                "success": False,
                "stage": "validation",
                "error": f"Invalid SHA format. Expected 40 hex chars, got '{target_sha}'"
            }

        # 2. Working tree cleanliness check (git status --porcelain must be empty)
        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=5
        )
        if status_res.returncode != 0:
            return {"success": False, "stage": "pre_check", "error": f"git status failed: {status_res.stderr.strip()}"}
        if status_res.stdout.strip():
            return {
                "success": False,
                "stage": "pre_check",
                "error": "Working tree is dirty (uncommitted changes present). Update rejected."
            }

        pre_pull_sha = self.get_local_head_sha()
        if not pre_pull_sha:
            return {"success": False, "stage": "pre_check", "error": "Unable to determine local HEAD SHA"}

        # 3. Fetch remote branch
        fetch_res = subprocess.run(
            ["git", "fetch", "origin", self.branch],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=30
        )
        if fetch_res.returncode != 0:
            return {"success": False, "stage": "git_fetch", "error": fetch_res.stderr.strip() or "git fetch failed"}

        # 4. Anti-staleness: Target SHA must be the current remote HEAD
        remote_head = self.get_remote_head_sha()
        if not remote_head:
            return {"success": False, "stage": "sha_staleness", "error": "Unable to determine remote HEAD SHA"}
        if remote_head != target_sha:
            return {
                "success": False,
                "stage": "sha_staleness",
                "error": f"Target SHA {target_sha[:7]} is no longer remote HEAD (current remote HEAD is {remote_head[:7]})"
            }

        # 5. Branch lineage: Pastikan SHA turunan origin/<branch>
        ancestor_check = subprocess.run(
            ["git", "merge-base", "--is-ancestor", target_sha, f"origin/{self.branch}"],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=5
        )
        if ancestor_check.returncode != 0:
            return {
                "success": False,
                "stage": "branch_verification",
                "error": f"Target SHA {target_sha[:7]} is not an ancestor of origin/{self.branch}"
            }

        # 6. Backup pip freeze if requirements.txt will change
        pre_freeze_data: Optional[str] = None
        pip_path = self.repo_dir / "venv/bin/pip"
        try:
            diff_check = subprocess.run(
                ["git", "diff", "--name-only", pre_pull_sha, target_sha],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=5
            )
            if "requirements.txt" in diff_check.stdout and pip_path.exists():
                freeze_res = subprocess.run(
                    [str(pip_path), "freeze"],
                    cwd=str(self.repo_dir),
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                if freeze_res.returncode == 0:
                    pre_freeze_data = freeze_res.stdout
        except Exception as e:
            logger.warning(f"pre-freeze check warning: {e}")

        # 7. Merge with --ff-only
        merge_res = subprocess.run(
            ["git", "merge", "--ff-only", target_sha],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=15
        )
        if merge_res.returncode != 0:
            return {
                "success": False,
                "stage": "git_merge",
                "error": f"Fast-forward merge failed: {merge_res.stderr.strip()}"
            }

        new_sha = self.get_local_head_sha()
        if new_sha != target_sha:
            self._rollback_to(pre_pull_sha, pre_freeze_data)
            return {
                "success": False,
                "stage": "sha_mismatch",
                "error": f"Local HEAD {new_sha[:7]} did not match target {target_sha[:7]}",
                "rolled_back_to": pre_pull_sha[:7]
            }

        # 8. Pre-flight Syntax Verification (py_compile)
        syntax_ok, syntax_err = self.validate_code_syntax()
        if not syntax_ok:
            logger.error(f"🚨 Pre-flight syntax check FAILED: {syntax_err}. Triggering automated rollback...")
            self._rollback_to(pre_pull_sha, pre_freeze_data)
            return {
                "success": False,
                "stage": "py_compile",
                "error": syntax_err,
                "rolled_back_to": pre_pull_sha[:7]
            }

        # 9. Update dependencies if requirements.txt changed
        if "requirements.txt" in diff_check.stdout and pip_path.exists():
            logger.info("📦 Updating python dependencies in venv...")
            pip_res = subprocess.run(
                [str(pip_path), "install", "-r", "requirements.txt"],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=90
            )
            if pip_res.returncode != 0:
                logger.error(f"🚨 Dependency update failed: {pip_res.stderr}. Rolling back...")
                self._rollback_to(pre_pull_sha, pre_freeze_data)
                return {
                    "success": False,
                    "stage": "pip_install",
                    "error": pip_res.stderr.strip()[:200],
                    "rolled_back_to": pre_pull_sha[:7]
                }

        # 10. Sanity Import Test (run in both Mac and Linux environments)
        import_test = subprocess.run(
            [sys.executable, "-c", "import main, core.config, ans.gitops_watcher"],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=10
        )
        if import_test.returncode != 0:
            logger.error(f"🚨 Sanity import test FAILED: {import_test.stderr}. Rolling back...")
            self._rollback_to(pre_pull_sha, pre_freeze_data)
            return {
                "success": False,
                "stage": "import_test",
                "error": import_test.stderr.strip()[:200] or "Module import test failed",
                "rolled_back_to": pre_pull_sha[:7]
            }

        # 11. Service Restart & Heartbeat Verification (on Linux systemd production)
        if sys.platform.startswith("linux"):
            restart_res = subprocess.run(
                ["sudo", "systemctl", "restart", "zura.service"],
                capture_output=True,
                text=True,
                timeout=15
            )
            if restart_res.returncode != 0:
                logger.error(f"🚨 zura.service restart failed: {restart_res.stderr}. Rolling back...")
                self._rollback_to(pre_pull_sha, pre_freeze_data)
                subprocess.run(["sudo", "systemctl", "restart", "zura.service"], capture_output=True, timeout=15)
                return {
                    "success": False,
                    "stage": "service_restart",
                    "error": f"systemctl restart failed: {restart_res.stderr.strip()[:200]}",
                    "rolled_back_to": pre_pull_sha[:7]
                }

            # Wait and verify heartbeat (up to 10 seconds)
            healthy = False
            for _ in range(10):
                time.sleep(1)
                chk = subprocess.run(
                    ["systemctl", "is-active", "zura.service"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if chk.stdout.strip() == "active":
                    healthy = True
                    break

            if not healthy:
                logger.error("🚨 zura.service heartbeat unhealthy after update. Rolling back...")
                self._rollback_to(pre_pull_sha, pre_freeze_data)
                subprocess.run(["sudo", "systemctl", "restart", "zura.service"], capture_output=True, timeout=15)
                return {
                    "success": False,
                    "stage": "heartbeat_verification",
                    "error": "zura.service is not active after update",
                    "rolled_back_to": pre_pull_sha[:7]
                }

        # 12. Record Audit Decision
        log_decision(
            domain="GitOps Guardian",
            trigger_event=f"L3 User approval for commit {target_sha[:7]}",
            decision_taken="Applied update after passing porcelain, lineage, py_compile, dependencies, import, and heartbeat tests",
            outcome=f"Updated successfully from {pre_pull_sha[:7]} to {new_sha[:7]}"
        )

        logger.info(f"✅ Update successfully applied and verified: {pre_pull_sha[:7]} -> {new_sha[:7]}")
        return {
            "success": True,
            "old_sha": pre_pull_sha[:7],
            "new_sha": new_sha[:7],
            "rolled_back_to": None
        }

    def _rollback_to(self, sha: str, pre_freeze_data: Optional[str] = None):
        """Emergency hard rollback to restore working tree and python environment."""
        try:
            subprocess.run(
                ["git", "reset", "--hard", sha],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=15
            )
            subprocess.run(
                ["git", "clean", "-fd"],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=15
            )
            logger.warning(f"⏪ Working tree hard-reset to commit {sha[:7]}")

            # Restore pip dependencies if saved
            if pre_freeze_data:
                pip_path = self.repo_dir / "venv/bin/pip"
                if pip_path.exists():
                    tmp_freeze = self.repo_dir / ".git/pre_rollback_freeze.txt"
                    tmp_freeze.write_text(pre_freeze_data)
                    subprocess.run(
                        [str(pip_path), "install", "-r", str(tmp_freeze)],
                        cwd=str(self.repo_dir),
                        capture_output=True,
                        text=True,
                        timeout=90
                    )
                    tmp_freeze.unlink(missing_ok=True)
                    logger.warning("⏪ Restored pre-update pip dependencies")

        except Exception as e:
            logger.critical(f"FATAL: Rollback to {sha[:7]} failed: {e}")


# Global instance
gitops_watcher = GitOpsWatcher()
