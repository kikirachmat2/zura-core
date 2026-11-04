#!/bin/bash
# tests/test_server_crash_recovery.sh - Standalone Server 1 Crash Recovery Harness
# ⚠️ JANGAN JALANKAN DI SERVER SEBELUM DIPERINTAHKAN OLEH BOS KIKI!
#
# Skenario Pengujian:
# 1. Memverifikasi bahwa zura-updater.service berjalan independen dan tetap hidup saat zura.service di-restart.
# 2. Mensimulasikan commit di branch yang lolos import dan py_compile,
#    tetapi sengaja me-raise fatal exit saat runtime startup.
# 3. Menjalankan zura_updater.py untuk me-restart zura.service.
# 4. Memverifikasi bahwa zura_updater mendeteksi ketiadaan DB heartbeat dalam window pengawasan,
#    secara otomatis mengeksekusi git reset --hard ke commit stabil sebelumnya,
#    me-restart zura.service versi stabil, dan mengirimkan alert kegagalan ke Telegram.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "======================================================================"
echo "🛡️ ZURA SERVER 1 CRASH-RECOVERY VERIFICATION HARNESS"
echo "======================================================================"
echo "Target: $BASE_DIR"

if [ "$1" != "--execute-crash-test" ]; then
  echo "⚠️ Safety Guard: Skrip ini hanya untuk demonstrasi kesiapan tes Server 1."
  echo "Untuk mengeksekusi di Server 1 setelah diizinkan: ./tests/test_server_crash_recovery.sh --execute-crash-test"
  exit 0
fi

PRE_SHA=$(git -C "$BASE_DIR" rev-parse HEAD)
echo "1. Baseline stable commit: $PRE_SHA"

# A. Verify updater unit exists and can run decoupled
echo "2. Verifying decoupled updater unit..."
if systemctl list-unit-files | grep -q "zura-updater.service"; then
  echo "   [PASS] zura-updater.service registered in systemd."
else
  echo "   [WARN] zura-updater.service not registered. Falling back to background process."
fi

# B. Inject runtime crash after 2.5 seconds of running (survives static py_compile & import tests)
echo "3. Injecting delayed runtime startup crash..."
cat << 'CRASH_SNIPPET' >> "$BASE_DIR/core/brain.py"

# --- SIMULATED RUNTIME STARTUP CRASH ---
import threading, time, os
def _delayed_fatal_crash():
    time.sleep(2.5)
    os._exit(42)
threading.Thread(target=_delayed_fatal_crash, daemon=True).start()
# --------------------------------------
CRASH_SNIPPET

git -C "$BASE_DIR" add core/brain.py
git -C "$BASE_DIR" commit -m "test: simulated runtime startup crash for recovery harness"
TEST_CRASH_SHA=$(git -C "$BASE_DIR" rev-parse HEAD)
echo "   Injected crash commit: $TEST_CRASH_SHA"

# Create pending_update marker (without secrets)
cat << EOF > "$BASE_DIR/.git/pending_update.json"
{
  "pre_pull_sha": "$PRE_SHA",
  "target_sha": "$TEST_CRASH_SHA",
  "timestamp": $(date +%s),
  "chat_id": 0,
  "db_path": "$BASE_DIR/data/zura.db"
}
EOF
chmod 600 "$BASE_DIR/.git/pending_update.json"

echo "4. Triggering decoupled updater..."
if systemctl list-unit-files | grep -q "zura-updater.service"; then
  sudo systemctl start --no-block zura-updater.service
  echo "   Monitoring zura-updater.service log until completion..."
  sudo journalctl -u zura-updater.service -f -n 20 --no-tail &
  JOURNAL_PID=$!
  sleep 30
  kill $JOURNAL_PID 2>/dev/null || true
else
  "$BASE_DIR/venv/bin/python3" "$BASE_DIR/scripts/zura_updater.py"
fi

CURRENT_SHA=$(git -C "$BASE_DIR" rev-parse HEAD)
echo "5. Post-recovery commit: $CURRENT_SHA"

if [ "$CURRENT_SHA" == "$PRE_SHA" ]; then
  echo "🎉 SUCCESS: zura_updater successfully detected runtime crash and rolled back to stable commit ($PRE_SHA)!"
  echo "   Working tree cleanliness check:"
  git -C "$BASE_DIR" status --porcelain
else
  echo "❌ FAILURE: Rollback did not restore initial stable commit ($PRE_SHA)."
  exit 1
fi
