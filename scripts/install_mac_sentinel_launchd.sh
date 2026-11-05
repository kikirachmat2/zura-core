#!/usr/bin/env bash
# scripts/install_mac_sentinel_launchd.sh - Persistent Mac Sentinel Installer
# Installs com.zura.macsentinel.plist into ~/Library/LaunchAgents/

set -euo pipefail

PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/com.zura.macsentinel.plist"
LOG_DIR="$HOME/.zura/logs"
WORKSPACE="/Users/kiki/Documents/Web Develop/Personal AI"
PYTHON_BIN="/usr/bin/python3"

if [[ -f "$WORKSPACE/venv/bin/python3" ]]; then
    PYTHON_BIN="$WORKSPACE/venv/bin/python3"
fi

mkdir -p "$PLIST_DIR"
mkdir -p "$LOG_DIR"

cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.zura.macsentinel</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$WORKSPACE/ans/mac_daemon.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$WORKSPACE</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/mac_sentinel.out.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/mac_sentinel.err.log</string>
</dict>
</plist>
EOF

chmod 644 "$PLIST_PATH"
echo "✅ Installed Mac Sentinel LaunchAgent at $PLIST_PATH"
echo "To load/activate: launchctl load -w $PLIST_PATH"
echo "To unload: launchctl unload $PLIST_PATH"
