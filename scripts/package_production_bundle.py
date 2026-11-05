#!/usr/bin/env python3
"""
scripts/package_production_bundle.py - Fase 0.8: Pre-flight & Production Tarball Packager
Per Zura Charter v2:
1. Runs full pre-flight verification:
   - Checks file permissions (.env 0600, data/ 0700).
   - Scans for private keys / secrets in tracked files.
   - Runs full unittest suite (aborts if any test fails).
2. Generates verified release bundle tarball (zura_release_bundle.tar.gz)
   excluding venv, local sqlite databases, and git logs.
3. Generates release manifest and SHA-256 checksum.
"""

import os
import sys
import tarfile
import hashlib
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import core.config as config


def run_preflight_checks() -> bool:
    print("🔍 [1/3] Running Pre-Flight Verifications...")

    # 1. Check permissions
    perm_res = config.enforce_file_permissions(strict=False)
    print(f"  ✓ Permissions checked: {perm_res}")

    # 2. Check for private keys in tracked repo
    print("  ✓ Scanning codebase for exposed private key markers...")
    key_pattern = "----" + "-BEGIN [A-Z ]*PRIVATE KEY-----"
    res = subprocess.run(
        ["git", "grep", "-i", "-E", key_pattern, "--", ":!scripts/package_production_bundle.py"],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True
    )
    if res.returncode == 0 and res.stdout.strip():
        print(f"  ❌ CRITICAL: Private key detected in repo:\n{res.stdout}")
        return False
    print("  ✓ Zero private keys in repository.")

    # 3. Run full unittest suite
    print("  ✓ Running full test discovery suite...")
    test_res = subprocess.run([sys.executable, "-m", "unittest", "discover", "tests"], cwd=str(BASE_DIR), capture_output=True, text=True)
    if test_res.returncode != 0:
        print(f"  ❌ Unit tests failed:\n{test_res.stderr}\n{test_res.stdout}")
        return False
    print("  ✓ All unit tests passed cleanly.")
    return True


def create_release_tarball() -> Path:
    print("\n📦 [2/3] Creating Release Tarball Bundle...")
    output_bundle = BASE_DIR / "zura_release_bundle.tar.gz"

    exclude_patterns = [
        "venv", ".git", "__pycache__", ".pytest_cache", ".DS_Store",
        "data/zura.db", "data/zura.db.bak_05b", "data/kisahkomisi.db",
        "data/Buku_Kas_Bos_Kiki.csv", "temp_voice", "*.pyc",
        "zura_release_bundle.tar.gz", "zura_release_manifest.txt"
    ]

    def filter_bundle(tarinfo):
        basename = os.path.basename(tarinfo.name)
        if basename == ".env":
            return None
        for pattern in exclude_patterns:
            if pattern in tarinfo.name:
                return None
        return tarinfo

    with tarfile.open(output_bundle, "w:gz") as tar:
        tar.add(BASE_DIR, arcname="zura-core", filter=filter_bundle)

    sha256 = hashlib.sha256(output_bundle.read_bytes()).hexdigest()
    print(f"  ✓ Bundle created: {output_bundle.name} ({output_bundle.stat().st_size:,} bytes)")
    print(f"  ✓ SHA-256 Checksum: {sha256}")

    # Write manifest
    manifest_file = BASE_DIR / "zura_release_manifest.txt"
    manifest_file.write_text(f"ZURA PRODUCTION RELEASE BUNDLE\nSHA-256: {sha256}\nTimestamp: {os.path.getmtime(output_bundle)}\n")
    print(f"  ✓ Manifest written to {manifest_file.name}")
    return output_bundle


def print_deploy_instructions(bundle_path: Path):
    print("\n🚀 [3/3] Production Deployment Procedure (Manual Safe Deploy):")
    print("=" * 60)
    print("1. Salin bundle ke Server 1 via Tailscale:")
    print(f"   scp {bundle_path.name} ubuntu@100.x.y.z:/home/ubuntu/")
    print("\n2. SSH ke Server 1 dan stop service:")
    print("   ssh ubuntu@100.x.y.z")
    print("   sudo systemctl stop zura.service")
    print("\n3. Backup database & env lama di server:")
    print("   cp /home/ubuntu/zura-core/data/zura.db /home/ubuntu/zura.db.bak_pre_deploy")
    print("   cp /home/ubuntu/zura-core/.env /home/ubuntu/.env.bak_pre_deploy")
    print("\n4. Verifikasi isi tarball sebelum ekstrak:")
    print(f"   tar -tzf /home/ubuntu/{bundle_path.name} | head -n 20")
    print("\n5. Ekstrak bundle dan update venv:")
    print(f"   tar -xzf /home/ubuntu/{bundle_path.name} -C /home/ubuntu/")
    print("   cd /home/ubuntu/zura-core")
    print("   ./venv/bin/pip install -r requirements.txt")
    print("\n6. Jalankan smoke test sebelum start:")
    print("   ./venv/bin/python3 -m unittest discover tests")
    print("\n7. Start service & verifikasi heartbeat:")
    print("   sudo systemctl start zura.service")
    print("   sudo systemctl status zura.service")
    print("=" * 60)


def main():
    if not run_preflight_checks():
        print("❌ Pre-flight check failed! Release packaging aborted.")
        sys.exit(1)

    bundle = create_release_tarball()
    print_deploy_instructions(bundle)


if __name__ == "__main__":
    main()
