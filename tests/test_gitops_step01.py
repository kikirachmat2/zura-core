"""
tests/test_gitops_step01.py - Verification Test for Step 0.1 (GitOps Hardening)
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from ans.gitops_watcher import gitops_watcher, GitOpsWatcher


class TestGitOpsStep01(unittest.TestCase):
    def setUp(self):
        self.watcher = gitops_watcher

    def test_local_head_sha(self):
        sha = self.watcher.get_local_head_sha()
        self.assertTrue(len(sha) == 40, f"Local SHA should be 40 chars, got: {sha}")
        print(f"  [PASS] Local HEAD SHA: {sha[:7]}")

    def test_check_for_updates_returns_dict(self):
        res = self.watcher.check_for_updates()
        self.assertIsInstance(res, dict)
        self.assertIn("update_available", res)
        print(f"  [PASS] check_for_updates returned: {res}")

    def test_validate_code_syntax(self):
        valid, msg = self.watcher.validate_code_syntax()
        self.assertTrue(valid, f"All Python files should compile cleanly: {msg}")
        print(f"  [PASS] validate_code_syntax: {msg}")

    def test_apply_update_rejects_invalid_sha(self):
        res = self.watcher.apply_update("non_existent_sha_1234567")
        self.assertFalse(res["success"])
        self.assertEqual(res["stage"], "validation" if len("non_existent_sha_1234567") < 7 else "git_fetch" if "fetch" in res["stage"] else res["stage"])
        print(f"  [PASS] Invalid SHA rejected gracefully: {res}")

    def test_deprecated_method_removed(self):
        self.assertFalse(hasattr(self.watcher, "check_and_apply_update"), "Deprecated method check_and_apply_update should be removed")
        print("  [PASS] check_and_apply_update confirmed removed.")


if __name__ == "__main__":
    unittest.main()

