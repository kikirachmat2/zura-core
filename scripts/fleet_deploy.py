#!/usr/bin/env python3
"""
scripts/fleet_deploy.py - Fleet CLI for Zura, KisahKomisi (Threads), and KiBot V3
Usage:
  python3 scripts/fleet_deploy.py --status
  python3 scripts/fleet_deploy.py --deploy zura|threads|kibot|all
  python3 scripts/fleet_deploy.py --sync "commit message"
"""

import sys
import argparse
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from ops.fleet_manager import (
    get_fleet_git_status,
    commit_fleet_repo,
    deploy_fleet_repo,
    sync_and_deploy_all
)


def main():
    parser = argparse.ArgumentParser(description="Fleet Code & Deployment Manager for Bos Kiki")
    parser.add_argument("--status", action="store_true", help="Inspect git status of all 3 repositories")
    parser.add_argument("--commit", nargs=2, metavar=("BOT", "MSG"), help="Commit changes to target bot (zura/threads/kibot)")
    parser.add_argument("--deploy", choices=["zura", "threads", "kibot", "all"], help="Deploy target bot or all to Server 1")
    parser.add_argument("--sync", metavar="MSG", help="Autonomous commit, sync, and reload all repos on Server 1")

    args = parser.parse_args()

    if args.status or len(sys.argv) == 1:
        statuses = get_fleet_git_status()
        print("\n================ FLEET GIT & CODE STATUS ================")
        for bot_id, st in statuses.items():
            if "error" in st:
                print(f"❌ [{bot_id.upper()}] Error: {st['error']}")
                continue
            icon = "🟡 MODIFIED" if st["has_changes"] else "🟢 CLEAN"
            print(f"{icon} [{bot_id.upper()}] {st['name']}")
            print(f"   ├ Branch: {st['branch']} ({st['commit']})")
            print(f"   ├ Path:   {st['path']}")
            print(f"   └ Uncommitted changes: {st['modified_files_count']}")
            if st["changes"]:
                for c in st["changes"]:
                    print(f"     • {c}")
        print("=========================================================\n")
        return

    if args.commit:
        bot, msg = args.commit
        res = commit_fleet_repo(bot, msg)
        print(f"[{bot}] Commit Result: {res}")
        return

    if args.deploy:
        targets = ["zura", "threads", "kibot"] if args.deploy == "all" else [args.deploy]
        for t in targets:
            print(f"🚀 Deploying [{t}] to Server 1...")
            res = deploy_fleet_repo(t)
            status_badge = "✅ SUCCESS" if res["success"] else "❌ FAILED"
            print(f"   └ {status_badge} ({res.get('service_status')})")
        return

    if args.sync:
        print(f"⚡ Running full autonomous fleet sync & deploy (msg: '{args.sync}')...")
        results = sync_and_deploy_all(args.sync)
        for k, v in results.items():
            print(f"• {k}: {v.get('service_status', v.get('success'))}")


if __name__ == "__main__":
    main()

