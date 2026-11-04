#!/bin/bash
# scripts/zura_call.sh - Quick trigger for Zura Siri Voice on Mac

PROJECT_DIR="/Users/kiki/Documents/Web Develop/Personal AI"
cd "$PROJECT_DIR"
"$PROJECT_DIR/venv/bin/python3" "$PROJECT_DIR/voice/zura_siri.py" "$@"

