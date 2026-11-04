#!/bin/bash
# scripts/zura_call.sh - Quick trigger for Zura Siri Voice on Mac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"
"$PROJECT_DIR/venv/bin/python3" "$PROJECT_DIR/voice/zura_siri.py" "$@"
