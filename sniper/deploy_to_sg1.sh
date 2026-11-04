#!/bin/bash
# sniper/deploy_to_sg1.sh - Deploy Batam Sniper to Server 1
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env if present
if [ -f "$BASE_DIR/.env" ]; then
  set -a
  source "$BASE_DIR/.env"
  set +a
fi

SERVER_IP="${SERVER1_HOST:-}"
SERVER_USER="${SERVER1_USER:-ubuntu}"
SSH_KEY="${SERVER1_KEY:-$HOME/.ssh/id_rsa}"
REMOTE_DIR="/home/ubuntu/zura-sniper"

if [ -z "$SERVER_IP" ]; then
  echo "❌ Error: SERVER1_HOST is not set in environment or .env"
  exit 1
fi

echo "🚀 [1/3] Syncing Batam Sniper & OCI credentials to Server 1 ($SERVER_IP)..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$SERVER_USER@$SERVER_IP" "mkdir -p $REMOTE_DIR ~/.oci"

# Copy OCI credentials and sniper script
if [ -f "$HOME/.oci/batam.pem" ]; then
  scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "$HOME/.oci/batam.pem" "$SERVER_USER@$SERVER_IP:~/.oci/"
fi
if [ -f "$HOME/.oci/config" ]; then
  scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "$HOME/.oci/config" "$SERVER_USER@$SERVER_IP:~/.oci/"
fi
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "$BASE_DIR/sniper/batam_sniper.py" "$SERVER_USER@$SERVER_IP:$REMOTE_DIR/"

echo "📦 [2/3] Setting up Python virtual environment & dependencies on Server 1..."
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_IP" "bash -s" << 'REMOTE_SETUP'
  cd /home/ubuntu/zura-sniper
  if [ ! -d "venv" ]; then
    python3 -m venv venv
  fi
  ./venv/bin/pip install --upgrade pip requests oci
REMOTE_SETUP

echo "⚙️ [3/3] Creating and starting systemd service (zura-batam-sniper.service)..."
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_IP" "bash -s" << 'REMOTE_SYSTEMD'
  cat << 'SERVICE' | sudo tee /etc/systemd/system/zura-batam-sniper.service > /dev/null
[Unit]
Description=Zura 24/7 Batam Ampere A1 Sniper Daemon
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/zura-sniper
ExecStart=/home/ubuntu/zura-sniper/venv/bin/python3 /home/ubuntu/zura-sniper/batam_sniper.py
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
SERVICE

  sudo systemctl daemon-reload
  sudo systemctl enable --now zura-batam-sniper.service
  sudo systemctl status zura-batam-sniper.service --no-pager
REMOTE_SYSTEMD
