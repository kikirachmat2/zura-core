"""
tests/test_gitops_01b.py - Comprehensive Unit Tests for GitOps Guardian 0.1b
Tests against isolated temporary bare remote:
1. Working tree kotor -> ditolak
2. SHA lama setelah remote maju (anti-staleness) -> ditolak
3. Commit syntax error -> auto-rollback ke pre-SHA dan tree identik
4. Commit import failure -> auto-rollback ke pre-SHA dan tree identik
5. Commit bagus -> sukses diverifikasi dan diterapkan
"""

import os
import sys
import shutil
import tempfile
import unittest
import subprocess
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ans.gitops_watcher import GitOpsWatcher


class TestGitOps01bIsolated(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="zura_gitops_test_")
        self.tmp_path = Path(self.temp_dir)

        # 1. Create bare remote
        self.bare_dir = self.tmp_path / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.bare_dir)], check=True, capture_output=True)
        subprocess.run(["git", "symbolic-ref", "HEAD", "refs/heads/main"], cwd=str(self.bare_dir), check=True)

        # 2. Create dev clone to seed repo and push commits
        self.dev_dir = self.tmp_path / "dev_repo"
        subprocess.run(["git", "clone", str(self.bare_dir), str(self.dev_dir)], check=True, capture_output=True)

        # Setup git identity
        subprocess.run(["git", "config", "user.name", "Zura Tester"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "config", "user.email", "tester@zura.local"], cwd=str(self.dev_dir), check=True)

        # Populate minimal runnable Zura skeleton in dev_repo
        (self.dev_dir / "core").mkdir(parents=True, exist_ok=True)
        (self.dev_dir / "ans").mkdir(parents=True, exist_ok=True)
        (self.dev_dir / "main.py").write_text("#!/usr/bin/env python3\nprint('Zura Test Node')\n")
        (self.dev_dir / "core/__init__.py").write_text("")
        (self.dev_dir / "core/config.py").write_text(f"from pathlib import Path\nBASE_DIR = Path('{self.dev_dir}')\nGITOPS_BRANCH = 'main'\nTELEGRAM_BOT_TOKEN = ''\nTELEGRAM_CHAT_ID = 0\nDB_PATH = BASE_DIR / 'zura.db'\n")
        (self.dev_dir / "core/memory.py").write_text("def log_decision(*args, **kwargs): pass\ndef set_state(*args, **kwargs): pass\ndef get_state(*args, **kwargs): return ''\n")
        
        # Copy gitops_watcher.py and core/actuator.py from project
        shutil.copy(PROJECT_ROOT / "ans/gitops_watcher.py", self.dev_dir / "ans/gitops_watcher.py")
        shutil.copy(PROJECT_ROOT / "core/actuator.py", self.dev_dir / "core/actuator.py")

        subprocess.run(["git", "add", "."], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(self.dev_dir), check=True)

        # 3. Create prod clone (target monitored node)
        self.prod_dir = self.tmp_path / "prod_repo"
        subprocess.run(["git", "clone", "-b", "main", str(self.bare_dir), str(self.prod_dir)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Zura Prod"], cwd=str(self.prod_dir), check=True)
        subprocess.run(["git", "config", "user.email", "prod@zura.local"], cwd=str(self.prod_dir), check=True)

        # Update core/config.py in prod_dir to point to prod_dir
        (self.prod_dir / "core").mkdir(parents=True, exist_ok=True)
        (self.prod_dir / "core/config.py").write_text(f"from pathlib import Path\nBASE_DIR = Path('{self.prod_dir}')\nGITOPS_BRANCH = 'main'\nTELEGRAM_BOT_TOKEN = ''\nTELEGRAM_CHAT_ID = 0\nDB_PATH = BASE_DIR / 'zura.db'\n")
        subprocess.run(["git", "commit", "-am", "configure prod BASE_DIR"], cwd=str(self.prod_dir), check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=str(self.prod_dir), check=True)

        # Pull back into dev_repo so both are in sync
        subprocess.run(["git", "pull", "origin", "main"], cwd=str(self.dev_dir), check=True, capture_output=True)

        # Instantiate GitOpsWatcher on prod_dir
        self.watcher = GitOpsWatcher(repo_dir=self.prod_dir, branch="main")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_dirty_working_tree_rejected(self):
        """Tolak apply kalau git status --porcelain tidak kosong."""
        # Create uncommitted dirty file in prod
        dirty_file = self.prod_dir / "untracked_file.txt"
        dirty_file.write_text("dirty state")

        # Push valid commit from dev
        (self.dev_dir / "dummy.txt").write_text("new content")
        subprocess.run(["git", "add", "dummy.txt"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "commit", "-m", "update"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=str(self.dev_dir), check=True)
        
        target_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.dev_dir), capture_output=True, text=True).stdout.strip()

        res = self.watcher.apply_update(target_sha)
        self.assertFalse(res["success"])
        self.assertEqual(res["stage"], "pre_check")
        self.assertIn("Working tree is dirty", res["error"])
        print("\n  [PASS 1] Dirty working tree rejected gracefully.")

    def test_02_stale_sha_rejected(self):
        """SHA lama setelah remote maju -> ditolak (anti-staleness)."""
        # Push commit B
        (self.dev_dir / "file_b.txt").write_text("content B")
        subprocess.run(["git", "add", "file_b.txt"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "commit", "-m", "commit B"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=str(self.dev_dir), check=True)
        stale_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.dev_dir), capture_output=True, text=True).stdout.strip()

        # Push commit C (remote advances further)
        (self.dev_dir / "file_c.txt").write_text("content C")
        subprocess.run(["git", "add", "file_c.txt"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "commit", "-m", "commit C"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=str(self.dev_dir), check=True)

        # Attempt to apply stale commit B
        res = self.watcher.apply_update(stale_sha)
        self.assertFalse(res["success"])
        self.assertEqual(res["stage"], "sha_staleness")
        self.assertIn("no longer remote HEAD", res["error"])
        print("\n  [PASS 2] Stale SHA after remote advanced rejected gracefully.")

    def test_03_syntax_error_rollback(self):
        """Commit syntax error -> rollback ke pre-SHA dan working tree identik."""
        pre_sha = self.watcher.get_local_head_sha()

        # Dev pushes broken python syntax
        (self.dev_dir / "broken_syntax.py").write_text("def broken_func(:\n    pass syntax error!!\n")
        subprocess.run(["git", "add", "broken_syntax.py"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "commit", "-m", "bad syntax commit"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=str(self.dev_dir), check=True)
        bad_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.dev_dir), capture_output=True, text=True).stdout.strip()

        res = self.watcher.apply_update(bad_sha)
        self.assertFalse(res["success"])
        self.assertEqual(res["stage"], "py_compile")
        self.assertIn("Syntax error", res["error"])

        # Verify rollback: HEAD must equal pre_sha
        current_sha = self.watcher.get_local_head_sha()
        self.assertEqual(current_sha, pre_sha, f"Expected HEAD {pre_sha}, got {current_sha}")

        # Verify tree is clean and identical
        porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=str(self.prod_dir), capture_output=True, text=True).stdout.strip()
        self.assertEqual(porcelain, "", "Working tree must be clean after rollback")
        self.assertFalse((self.prod_dir / "broken_syntax.py").exists(), "Broken file must be removed after rollback")

        diff = subprocess.run(["git", "diff", pre_sha], cwd=str(self.prod_dir), capture_output=True, text=True).stdout.strip()
        self.assertEqual(diff, "", "Diff against pre_sha must be empty")
        print("\n  [PASS 3] Syntax error commit caught and hard-rolled back cleanly.")

    def test_04_import_failure_rollback(self):
        """Commit yang bikin import gagal -> rollback ke pre-SHA dan tree identik."""
        pre_sha = self.watcher.get_local_head_sha()

        # Dev pushes broken module that crashes on import
        (self.dev_dir / "toxic_module.py").write_text("raise RuntimeError('Fatal crash on import!')\n")
        # dev modifies main.py to import toxic_module
        (self.dev_dir / "main.py").write_text("import toxic_module\n")
        subprocess.run(["git", "add", "toxic_module.py", "main.py"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "commit", "-m", "bad import commit"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=str(self.dev_dir), check=True)
        bad_import_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.dev_dir), capture_output=True, text=True).stdout.strip()

        res = self.watcher.apply_update(bad_import_sha)
        self.assertFalse(res["success"])
        self.assertEqual(res["stage"], "import_test")

        # Verify rollback: HEAD must equal pre_sha
        current_sha = self.watcher.get_local_head_sha()
        self.assertEqual(current_sha, pre_sha)
        self.assertFalse((self.prod_dir / "toxic_module.py").exists())
        diff = subprocess.run(["git", "diff", pre_sha], cwd=str(self.prod_dir), capture_output=True, text=True).stdout.strip()
        self.assertEqual(diff, "", "Diff against pre_sha must be empty")
        print("\n  [PASS 4] Import failure caught and hard-rolled back cleanly.")

    def test_05_clean_commit_success(self):
        """Commit bagus -> sukses diverifikasi dan diterapkan."""
        # Dev pushes a clean new feature
        (self.dev_dir / "clean_feature.py").write_text("def get_status():\n    return 'operational'\n")
        subprocess.run(["git", "add", "clean_feature.py"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "commit", "-m", "feat: clean operational feature"], cwd=str(self.dev_dir), check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=str(self.dev_dir), check=True)
        good_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.dev_dir), capture_output=True, text=True).stdout.strip()

        res = self.watcher.apply_update(good_sha)
        self.assertTrue(res["success"])
        self.assertEqual(res["new_sha"], good_sha[:7])
        self.assertEqual(self.watcher.get_local_head_sha(), good_sha)
        self.assertTrue((self.prod_dir / "clean_feature.py").exists())
        print("\n  [PASS 5] Clean commit successfully verified, fast-forwarded, and applied.")


if __name__ == "__main__":
    unittest.main()

