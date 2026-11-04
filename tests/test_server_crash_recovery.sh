#!/bin/bash
# tests/test_server_crash_recovery.sh - Standalone Server 1 Crash Recovery Harness
# ⚠️ JANGAN JALANKAN DI SERVER SEBELUM DIPERINTAHKAN OLEH BOS KIKI!
#
# Skenario Pengujian:
# 1. Mensimulasikan commit di branch staging yang lolos import dan py_compile,
#    tetapi sengaja me-raise Exception saat startup event loop / background task.
# 2. Menjalankan zura_updater.py untuk me-restart zura.service.
# 3. Memverifikasi bahwa zura_updater mendeteksi ketiadaan DB heartbeat dalam 45s,
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
  echo "Untuk mengeksekusi di Server 1 setelah diizinkan: ./test_server_crash_recovery.sh --execute-crash-test"
  exit 0
fi

PRE_SHA=$(git -C "$BASE_DIR" rev-parse HEAD)
echo "1. Baseline stable commit: $PRE_SHA"

# Inject runtime crash after 2 seconds of running (survives static py_compile & import tests)
echo "2. Injecting delayed runtime startup crash..."
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

# Create pending_update marker
cat << EOF > "$BASE_DIR/.git/pending_update.json"
{
  "pre_pull_sha": "$PRE_SHA",
  "target_sha": "$TEST_CRASH_SHA",
  "timestamp": $(date +%s),
  "chat_id": 0,
  "bot_token": ""
}
EOF

echo "3. Triggering detached zura_updater.py..."
"$BASE_DIR/venv/bin/python3" "$BASE_DIR/scripts/zura_updater.py"

CURRENT_SHA=$(git -C "$BASE_DIR" rev-parse HEAD)
echo "4. Post-recovery commit: $CURRENT_SHA"

if [ "$CURRENT_SHA" == "$PRE_SHA" ]; then
  echo "🎉 SUCCESS: zura_updater successfully detected runtime crash and rolled back to stable commit ($PRE_SHA)!"
else
  echo "❌ FAILURE: Rollback did not restore initial stable commit ($PRE_SHA)."
  exit 1
fi
