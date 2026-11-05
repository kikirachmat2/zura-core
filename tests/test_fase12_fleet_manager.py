"""
tests/test_fase12_fleet_manager.py - Unit Tests for Multi-Repo Fleet Manager
Verifies git status detection, commit helpers, and deploy orchestrator for Zura, Threads, and KiBot.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from ops.fleet_manager import (
    FLEET_REPOS,
    get_fleet_git_status,
    commit_fleet_repo,
    deploy_fleet_repo,
    run_local_cmd
)


class TestFleetManager(unittest.TestCase):

    def test_fleet_repos_configuration(self):
        """Verifies that all three core bots are registered with correct paths."""
        self.assertIn("zura", FLEET_REPOS)
        self.assertIn("threads", FLEET_REPOS)
        self.assertIn("kibot", FLEET_REPOS)

        for bot_id, cfg in FLEET_REPOS.items():
            self.assertIn("name", cfg)
            self.assertIn("local_path", cfg)
            self.assertIn("remote_path", cfg)
            self.assertIn("restart_cmd", cfg)
            self.assertIn("exclude", cfg)

    def test_get_fleet_git_status(self):
        """Ensures get_fleet_git_status inspects all registered repositories."""
        statuses = get_fleet_git_status()
        self.assertIn("zura", statuses)
        self.assertIn("threads", statuses)
        self.assertIn("kibot", statuses)

        zura_st = statuses["zura"]
        self.assertIn("branch", zura_st)
        self.assertIn("commit", zura_st)
        self.assertIn("has_changes", zura_st)

    @patch("ops.fleet_manager.run_local_cmd")
    def test_commit_fleet_repo_success(self, mock_run):
        """Tests staging and committing code in a fleet repository."""
        # 1. git add -> success
        # 2. git status -> has changes
        # 3. git commit -> success
        mock_run.side_effect = [
            {"success": True, "stdout": "", "stderr": ""},
            {"success": True, "stdout": "M file.py", "stderr": ""},
            {"success": True, "stdout": "[main 12345] test commit", "stderr": ""}
        ]

        res = commit_fleet_repo("zura", "test commit")
        self.assertTrue(res["success"])
        self.assertIn("12345", res["stdout"])

    @patch("ops.fleet_manager.subprocess.run")
    @patch("ops.fleet_manager.run_remote_cmd")
    def test_deploy_fleet_repo(self, mock_remote, mock_subproc):
        """Tests rsync sync and remote service reload flow."""
        mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_remote.side_effect = [
            {"success": True, "stdout": "Restarted service", "stderr": ""},
            {"success": True, "stdout": "active", "stderr": ""}
        ]

        res = deploy_fleet_repo("zura")
        self.assertTrue(res["success"])
        self.assertEqual(res["service_status"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()

