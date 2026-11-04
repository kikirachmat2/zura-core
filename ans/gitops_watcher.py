"""
ans/gitops_watcher.py - Secure, Human-in-the-Loop GitOps Guardian
Complies with Zura Charter v2:
- Zero auto-pull: Autonomous code application is strictly prohibited (L3 Guardrail).
- Detection only: Checks remote commit SHA using ultra-low-bandwidth `git ls-remote`.
- Human Approval: Pulls ONLY upon explicit user approval tied to target SHA.
- Pre-flight Sanity: Runs py_compile on all python files before accepting changes.
- Automated Rollback: Instantly reverts to previous HEAD if syntax check or import test fails.
"""

import os
import sys
import subprocess
import logging
import py_compile
from pathlib import Path
from typing import Dict, Any, Tuple
from core.config import BASE_DIR, GITOPS_BRANCH
from core.memory import log_decision

logger = logging.getLogger("GitOpsWatcher")


class GitOpsWatcher:
    def __init__(self, check_interval_seconds: int = 600):
        self.repo_dir = BASE_DIR
        self.branch = GITOPS_BRANCH
        self.check_interval = check_interval_seconds
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
        except Exception as e:
            logger.debug(f"rev-parse HEAD error: {e}")
            return ""

    def get_remote_head_sha(self) -> str:
        """
        Queries remote HEAD SHA with minimal bandwidth (~500 bytes).
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

    def check_for_updates(self) -> Dict[str, Any]:
        """
        Pure telemetry check: compares local vs remote SHA.
        NEVER pulls code autonomously. Returns metadata for human review.
        """
        local_sha = self.get_local_head_sha()
        remote_sha = self.get_remote_head_sha()

        if not remote_sha or not local_sha:
            return {"update_available": False, "reason": "SHA check failed"}

        if remote_sha == local_sha:
            return {"update_available": False, "current_sha": local_sha[:7]}

        return {
            "update_available": True,
            "local_sha": local_sha[:7],
            "remote_sha": remote_sha[:7],
            "full_remote_sha": remote_sha,
            "branch": self.branch
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
        Includes sanity validation and automated hard-rollback on failure.
        """
        if not target_sha or len(target_sha) < 7:
            return {"success": False, "stage": "validation", "error": "Invalid target SHA specified"}

        pre_pull_sha = self.get_local_head_sha()
        if not pre_pull_sha:
            return {"success": False, "stage": "pre_check", "error": "Unable to determine local HEAD SHA"}

        logger.info(f"🛡️ Applying L3-authorized update to commit {target_sha[:7]} (Current HEAD: {pre_pull_sha[:7]})...")

        # 1. Fetch remote branch
        fetch_res = subprocess.run(
            ["git", "fetch", "origin", self.branch],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=30
        )
        if fetch_res.returncode != 0:
            return {"success": False, "stage": "git_fetch", "error": fetch_res.stderr.strip() or "git fetch failed"}

        # 2. Verify target SHA exists in remote commits
        rev_check = subprocess.run(
            ["git", "rev-parse", "--verify", f"{target_sha}^{{commit}}"],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=5
        )
        if rev_check.returncode != 0:
            return {"success": False, "stage": "sha_verification", "error": f"Target SHA {target_sha[:7]} not found in repository"}

        verified_sha = rev_check.stdout.strip()

        # 3. Fast-forward pull
        pull_res = subprocess.run(
            ["git", "merge", "--ff-only", verified_sha],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=20
        )
        if pull_res.returncode != 0:
            # If fast-forward fails, abort without changing state
            return {
                "success": False,
                "stage": "git_merge",
                "error": f"Fast-forward merge failed (diverged tree): {pull_res.stderr.strip()}"
            }

        new_sha = self.get_local_head_sha()
        if not new_sha.startswith(target_sha[:7]):
            self._rollback_to(pre_pull_sha)
            return {
                "success": False,
                "stage": "sha_mismatch",
                "error": f"Checked out SHA {new_sha[:7]} did not match target {target_sha[:7]}",
                "rolled_back_to": pre_pull_sha[:7]
            }

        # 4. Pre-flight Syntax Verification (py_compile)
        syntax_ok, syntax_err = self.validate_code_syntax()
        if not syntax_ok:
            logger.error(f"🚨 Pre-flight syntax check FAILED: {syntax_err}. Triggering automated rollback...")
            self._rollback_to(pre_pull_sha)
            return {
                "success": False,
                "stage": "py_compile",
                "error": syntax_err,
                "rolled_back_to": pre_pull_sha[:7]
            }

        # 5. Check and update dependencies if requirements.txt changed
        try:
            diff_check = subprocess.run(
                ["git", "diff", "--name-only", pre_pull_sha, new_sha],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=5
            )
            if "requirements.txt" in diff_check.stdout:
                logger.info("📦 Updating python dependencies in venv...")
                pip_path = self.repo_dir / "venv/bin/pip"
                if pip_path.exists():
                    pip_res = subprocess.run(
                        [str(pip_path), "install", "-r", "requirements.txt"],
                        cwd=str(self.repo_dir),
                        capture_output=True,
                        text=True,
                        timeout=90
                    )
                    if pip_res.returncode != 0:
                        logger.error(f"🚨 Dependency update failed: {pip_res.stderr}. Rolling back...")
                        self._rollback_to(pre_pull_sha)
                        return {
                            "success": False,
                            "stage": "pip_install",
                            "error": pip_res.stderr.strip()[:200],
                            "rolled_back_to": pre_pull_sha[:7]
                        }
        except Exception as e:
            logger.warning(f"Dependency diff check warning: {e}")

        # 6. Sanity Import Test
        import_test = subprocess.run(
            [sys.executable, "-c", "import main, core.config, ans.gitops_watcher"],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=10
        )
        if import_test.returncode != 0:
            logger.error(f"🚨 Sanity import test FAILED: {import_test.stderr}. Rolling back...")
            self._rollback_to(pre_pull_sha)
            return {
                "success": False,
                "stage": "import_test",
                "error": import_test.stderr.strip()[:200] or "Module import test failed",
                "rolled_back_to": pre_pull_sha[:7]
            }

        # 7. Record Audit Decision
        log_decision(
            domain="GitOps Guardian",
            trigger_event=f"L3 User approval for commit {target_sha[:7]}",
            decision_taken="Applied update after passing py_compile, dependencies, and import tests",
            outcome=f"Updated successfully from {pre_pull_sha[:7]} to {new_sha[:7]}"
        )

        logger.info(f"✅ Update successfully applied and verified: {pre_pull_sha[:7]} -> {new_sha[:7]}")
        return {
            "success": True,
            "old_sha": pre_pull_sha[:7],
            "new_sha": new_sha[:7],
            "rolled_back_to": None
        }

    def _rollback_to(self, sha: str):
        """Emergency hard rollback to restore working tree to a known good commit."""
        try:
            subprocess.run(
                ["git", "reset", "--hard", sha],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=15
            )
            logger.warning(f"⏪ Working tree hard-reset to commit {sha[:7]}")
        except Exception as e:
            logger.critical(f"FATAL: Rollback to {sha[:7]} failed: {e}")

    def check_and_apply_update(self) -> Dict[str, Any]:
        """DEPRECATED: Auto-pull disabled per Charter v2 (L3 Guardrail). Calls check_for_updates."""
        logger.warning("check_and_apply_update called but autonomous pull is disabled. Use check_for_updates.")
        return self.check_for_updates()


# Global instance
gitops_watcher = GitOpsWatcher()
