#!/bin/bash
# scripts/deploy_zura_to_server.sh - Deploy ZURA Core 24/7 to Server 1 (OCI Singapore)
set -e

SERVER_IP="${SERVER1_HOST:-your_server_ip}"
SERVER_USER="${SERVER1_USER:-ubuntu}"
SSH_KEY="${SERVER1_KEY:-$HOME/.ssh/id_rsa}"
REMOTE_DIR="/home/ubuntu/zura-core"

echo "🚀 [1/4] Syncing Zura codebase & environment to Server 1 ($SERVER_IP)..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$SERVER_USER@$SERVER_IP" "mkdir -p $REMOTE_DIR/logs $REMOTE_DIR/temp_voice $REMOTE_DIR/data"

rsync -avz -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
  --exclude 'venv' \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude '*.db' \
  --exclude 'logs/*.log' \
  --exclude 'temp_voice/*.mp3' \
  "/Users/kiki/Documents/Web Develop/Personal AI/" "$SERVER_USER@$SERVER_IP:$REMOTE_DIR/"

# Copy .env explicitly
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "/Users/kiki/Documents/Web Develop/Personal AI/.env" "$SERVER_USER@$SERVER_IP:$REMOTE_DIR/.env"

echo "📦 [2/4] Setting up Python virtual environment & dependencies on Server 1..."
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_IP" "bash -s" << 'REMOTE_SETUP'
  cd /home/ubuntu/zura-core
  if [ ! -d "venv" ]; then
    python3 -m venv venv
  fi
  ./venv/bin/pip install --upgrade pip
  ./venv/bin/pip install -r requirements.txt
REMOTE_SETUP

echo "⚙️ [3/4] Installing systemd service (zura.service) on Server 1..."
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_IP" "bash -s" << 'REMOTE_SYSTEMD'
  cat << 'SERVICE' | sudo tee /etc/systemd/system/zura.service > /dev/null
[Unit]
Description=ZURA Autonomous Personal AI Core Engine
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/zura-core
ExecStart=/home/ubuntu/zura-core/venv/bin/python3 /home/ubuntu/zura-core/main.py
Restart=always
RestartSec=10

# Security and resource safeguards
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
SERVICE

  sudo systemctl daemon-reload
  sudo systemctl enable --now zura.service
  sudo systemctl restart zura.service
  sudo systemctl status zura.service --no-pager
REMOTE_SYSTEMD

echo "✅ [4/4] ZURA IS NOW RUNNING 24/7 ON SERVER 1!"

