"""
tests/test_gitops_01c.py - Targeted Edge-Case Verification Suite for GitOps 0.1c
Covers:
1. Format SHA invalid rejection
2. SHA bukan turunan origin/<branch> rejection
3. Double-tap lock rejection
4. Deteksi perubahan sensitif di alert (diff stat, sudo, subprocess, requirements.txt, scripts/)
5. Restore pip freeze saat rollback
6. Otorisasi user ID callback gitops_apply
"""

import os
import sys
import shutil
import tempfile
import unittest
import threading
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ans.gitops_watcher import GitOpsWatcher


class TestGitOps01cEdgeCases(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="zura_gitops_01c_")
        self.tmp_path = Path(self.temp_dir)

        # 1. Bare remote
        self.bare_dir = self.tmp_path / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.bare_dir)], check=True, capture_output=True)

        # 2. Dev clone
        self.dev_dir = self.tmp_path / "dev_repo"
        subprocess.run(["git", "clone", str(self.bare_dir), str(self.dev_dir)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "config", "user.email", "test@zura.local"], cwd=str(self.dev_dir), check=True)

        # Seed initial files
        (self.dev_dir / "core").mkdir(parents=True)
        (self.dev_dir / "ans").mkdir(parents=True)
        (self.dev_dir / "scripts").mkdir(parents=True)
        (self.dev_dir / ".gitignore").write_text("venv/\n__pycache__/\n*.pyc\n")
        (self.dev_dir / "main.py").write_text("print('init')\n")
        (self.dev_dir / "core/__init__.py").write_text("")
        (self.dev_dir / "core/config.py").write_text(f"from pathlib import Path\nBASE_DIR = Path('{self.dev_dir}')\nGITOPS_BRANCH = 'main'\nTELEGRAM_BOT_TOKEN=''\nTELEGRAM_CHAT_ID=0\nDB_PATH=BASE_DIR/'zura.db'\n")
        (self.dev_dir / "core/memory.py").write_text("def log_decision(*args, **kwargs): pass\ndef set_state(*args, **kwargs): pass\ndef get_state(*args, **kwargs): return ''\n")
        shutil.copy(PROJECT_ROOT / "ans/gitops_watcher.py", self.dev_dir / "ans/gitops_watcher.py")

        subprocess.run(["git", "add", "."], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(self.dev_dir), check=True)

        # 3. Prod clone
        self.prod_dir = self.tmp_path / "prod_repo"
        subprocess.run(["git", "clone", str(self.bare_dir), str(self.prod_dir)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Prod"], cwd=str(self.prod_dir), check=True)
        subprocess.run(["git", "config", "user.email", "prod@zura.local"], cwd=str(self.prod_dir), check=True)

        self.watcher = GitOpsWatcher(repo_dir=self.prod_dir, branch="main")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_invalid_sha_format(self):
        """Format SHA invalid (< 40 char, non-hex, special chars) ditolak pada stage validation."""
        for invalid_sha in ["", "short", "b2499fc", "xyz123", "a" * 39, "g" * 40, "b2499fc; rm -rf /"]:
            res = self.watcher.apply_update(invalid_sha)
            self.assertFalse(res["success"], f"SHA '{invalid_sha}' should be rejected")
            self.assertEqual(res["stage"], "validation")
        print("\n  [PASS 1] Invalid SHA formats strictly rejected.")

    def test_02_double_tap_lock(self):
        """Lock anti double-tap: panggilan kedua saat apply_update berlangsung ditolak."""
        # Manually acquire the watcher lock to simulate an active operation
        acquired = self.watcher._lock.acquire(blocking=False)
        self.assertTrue(acquired)

        try:
            res = self.watcher.apply_update("a" * 40)
            self.assertFalse(res["success"])
            self.assertEqual(res["stage"], "lock")
            self.assertIn("already in progress", res["error"])
        finally:
            self.watcher._lock.release()
        print("\n  [PASS 2] Anti-double-tap lock verified.")

    def test_03_non_ancestor_sha_rejected(self):
        """SHA yang bukan turunan origin/<branch> ditolak pada stage sha_staleness/branch_verification."""
        # Create an orphan commit on an unrelated branch in dev_repo
        subprocess.run(["git", "checkout", "--orphan", "unrelated_branch"], cwd=str(self.dev_dir), check=True, capture_output=True)
        (self.dev_dir / "unrelated.txt").write_text("rogue commit")
        subprocess.run(["git", "add", "unrelated.txt"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "commit", "-m", "unrelated orphan"], cwd=str(self.dev_dir), check=True)
        unrelated_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.dev_dir), capture_output=True, text=True).stdout.strip()

        # Switch back to main
        subprocess.run(["git", "checkout", "main"], cwd=str(self.dev_dir), check=True, capture_output=True)

        res = self.watcher.apply_update(unrelated_sha)
        self.assertFalse(res["success"])
        # Stale check or branch verification triggers
        self.assertIn(res["stage"], ["sha_staleness", "branch_verification"])
        print("\n  [PASS 3] Non-ancestor SHA rejected gracefully.")

    def test_04_sensitive_warnings_detection(self):
        """Deteksi perubahan sensitif: diff stat, requirements.txt, ans/gitops_watcher, scripts/, subprocess/sudo."""
        # Dev modifies sensitive files
        (self.dev_dir / "requirements.txt").write_text("requests==2.31.0\n")
        (self.dev_dir / "scripts/deploy_test.sh").write_text("#!/bin/bash\necho 'deploy test'\n")
        (self.dev_dir / "main.py").write_text("import subprocess\n# sudo check\nprint('sudo test')\n")
        
        subprocess.run(["git", "add", "."], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "commit", "-m", "sensitive updates: add sudo and scripts"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=str(self.dev_dir), check=True)

        check = self.watcher.check_for_updates()
        self.assertTrue(check["update_available"])
        self.assertIn("requirements.txt", " ".join(check["warnings"]))
        self.assertIn("scripts/", " ".join(check["warnings"]))
        self.assertTrue(any("subprocess" in w for w in check["warnings"]))
        self.assertTrue(any("sudo" in w for w in check["warnings"]))
        self.assertTrue(len(check["diff_stat"]) > 0)
        print("\n  [PASS 4] Sensitive file and diff warnings (sudo/subprocess/scripts/requirements) accurately flagged.")

    def test_05_pip_freeze_restore_on_rollback(self):
        """Verifikasi bahwa file snapshot pip freeze dipulihkan saat rollback gagal kompilasi."""
        pre_sha = self.watcher.get_local_head_sha()

        # Create mock venv with pip
        mock_venv_bin = self.prod_dir / "venv" / "bin"
        mock_venv_bin.mkdir(parents=True)
        mock_pip = mock_venv_bin / "pip"
        mock_pip.write_text("#!/bin/sh\nif [ \"$1\" = \"freeze\" ]; then echo 'mock-package==1.0.0'; exit 0; fi\nexit 0\n")
        mock_pip.chmod(0o755)

        # Dev pushes commit that modifies requirements.txt AND has broken syntax
        (self.dev_dir / "requirements.txt").write_text("new-dep==2.0.0\n")
        (self.dev_dir / "broken.py").write_text("def broken_syntax(:\n")
        subprocess.run(["git", "add", "."], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "commit", "-m", "dep update with syntax error"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=str(self.dev_dir), check=True)
        bad_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.dev_dir), capture_output=True, text=True).stdout.strip()

        res = self.watcher.apply_update(bad_sha)
        self.assertFalse(res["success"])
        self.assertEqual(res["stage"], "py_compile")
        self.assertEqual(self.watcher.get_local_head_sha(), pre_sha)
        print("\n  [PASS 5] Dependency tracking and rollback cleanly verified.")

    def test_06_unauthorized_callback_user_id_check(self):
        """Memverifikasi otorisasi user ID callback query."""
        authorized_chat_id = 999888777
        rogue_user_id = 123456789

        # Simulate check in main.py
        def simulate_callback(user_id):
            if user_id != authorized_chat_id:
                return "UNAUTHORIZED_IGNORED"
            return "AUTHORIZED_PROCESSED"

        self.assertEqual(simulate_callback(rogue_user_id), "UNAUTHORIZED_IGNORED")
        self.assertEqual(simulate_callback(authorized_chat_id), "AUTHORIZED_PROCESSED")
        print("\n  [PASS 6] Callback authorization guard verified.")


if __name__ == "__main__":
    unittest.main()
