"""
core/config.py - Zura Configuration Loader
Loads environment variables and sets path constants.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory of Personal AI
BASE_DIR = Path(__file__).resolve().parent.parent

# 1. Load limits.env (Non-secret operational thresholds & rate limits)
LIMITS_PATH = BASE_DIR / "config/limits.env"
if LIMITS_PATH.exists():
    load_dotenv(dotenv_path=LIMITS_PATH, override=False)

# 2. Load .env file (Secret keys & private tokens)
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True)


def enforce_file_permissions(strict: bool = False) -> dict:
    """
    Enforces strict file permissions per Zura Charter v2 (Fase 0.6):
    - .env must be chmod 0600 (owner read/write only)
    - data/ directory must be chmod 0700 (owner access only)
    """
    results = {}
    if ENV_PATH.exists():
        current_mode = ENV_PATH.stat().st_mode & 0o777
        if current_mode & 0o077:  # Group or others have read/write/execute
            try:
                os.chmod(ENV_PATH, 0o600)
                results["env_permissions"] = f"tightened_to_0600 (was {oct(current_mode)})"
            except Exception as e:
                results["env_permissions"] = f"failed_to_chmod: {e}"
                if strict:
                    raise PermissionError(f"Insecure .env permissions ({oct(current_mode)}): {e}")
        else:
            results["env_permissions"] = "secure_0600"

    data_dir = BASE_DIR / "data"
    if data_dir.exists():
        current_mode = data_dir.stat().st_mode & 0o777
        if current_mode & 0o077:
            try:
                os.chmod(data_dir, 0o700)
                results["data_dir_permissions"] = f"tightened_to_0700 (was {oct(current_mode)})"
            except Exception as e:
                results["data_dir_permissions"] = f"failed_to_chmod: {e}"
                if strict:
                    raise PermissionError(f"Insecure data/ permissions ({oct(current_mode)}): {e}")
        else:
            results["data_dir_permissions"] = "secure_0700"

    return results


# Apply permission hardening on load
enforce_file_permissions(strict=False)

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
ZURA_BOT_USERNAME = os.getenv("ZURA_BOT_USERNAME", "zura_pa_bot")

# AI Engines
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Voice
VOICE_NAME_ID = os.getenv("VOICE_NAME_ID", "id-ID-GadisNeural")
VOICE_NAME_EN = os.getenv("VOICE_NAME_EN", "en-US-JennyNeural")
STT_MODEL = os.getenv("STT_MODEL", "whisper-large-v3")

# GitOps Configuration
GITOPS_BRANCH = os.getenv("GITOPS_BRANCH", "main")

# Multi-Server Nodes
SERVER1_HOST = os.getenv("SERVER1_HOST", "")
SERVER1_TAILSCALE = os.getenv("SERVER1_TAILSCALE", "")
SERVER1_USER = os.getenv("SERVER1_USER", "ubuntu")
SERVER1_KEY = os.getenv("SERVER1_KEY", str(Path.home() / ".ssh/id_rsa"))

SERVER2_HOST = os.getenv("SERVER2_HOST", "")
SERVER2_USER = os.getenv("SERVER2_USER", "ubuntu")
SERVER2_KEY = os.getenv("SERVER2_KEY", "")

# OCI Batam Sniper Target
OCI_BATAM_REGION = os.getenv("OCI_BATAM_REGION", "ap-batam-1")
OCI_BATAM_AD = os.getenv("OCI_BATAM_AD", "")
OCI_BATAM_SUBNET = os.getenv("OCI_BATAM_SUBNET", "")
OCI_BATAM_IMAGE = os.getenv("OCI_BATAM_IMAGE", "")
OCI_BATAM_COMPARTMENT = os.getenv("OCI_BATAM_COMPARTMENT", "")
OCI_BATAM_KEY = os.getenv("OCI_BATAM_KEY", "")

# Autonomic Thresholds
MAC_TEMP_MAX_C = float(os.getenv("MAC_TEMP_MAX_C", "62.0"))
MAC_TEMP_MIN_C = float(os.getenv("MAC_TEMP_MIN_C", "35.0"))
SERVER_RAM_MAX_PCT = float(os.getenv("SERVER_RAM_MAX_PCT", "85.0"))
SERVER_DISK_MAX_PCT = float(os.getenv("SERVER_DISK_MAX_PCT", "75.0"))
WIFI_MAX_LATENCY_MS = float(os.getenv("WIFI_MAX_LATENCY_MS", "90.0"))

# Personal Hotspot Failover
PERSONAL_HOTSPOT_SSID = os.getenv("PERSONAL_HOTSPOT_SSID", "PersonalHotspot")
PERSONAL_HOTSPOT_PASS = os.getenv("PERSONAL_HOTSPOT_PASS", "")

# Rate Limits (Cooldowns in Seconds)
RATE_LIMIT_SERVER_RESTART_SEC = float(os.getenv("RATE_LIMIT_SERVER_RESTART_SEC", "3600.0"))
RATE_LIMIT_KIBOT_RESTART_SEC = float(os.getenv("RATE_LIMIT_KIBOT_RESTART_SEC", "3600.0"))
RATE_LIMIT_KIBOT_TUNE_SEC = float(os.getenv("RATE_LIMIT_KIBOT_TUNE_SEC", "3600.0"))
RATE_LIMIT_WIFI_RECONNECT_SEC = float(os.getenv("RATE_LIMIT_WIFI_RECONNECT_SEC", "300.0"))
RATE_LIMIT_MAC_PURGE_CACHE_SEC = float(os.getenv("RATE_LIMIT_MAC_PURGE_CACHE_SEC", "600.0"))
RATE_LIMIT_THREADS_REPLENISH_SEC = float(os.getenv("RATE_LIMIT_THREADS_REPLENISH_SEC", "180.0"))

# Threads & Content Governance Limits
THREADS_DAILY_REPLENISH_CAP = int(os.getenv("THREADS_DAILY_REPLENISH_CAP", "5"))
THREADS_MIN_QUEUE_THRESHOLD = int(os.getenv("THREADS_MIN_QUEUE_THRESHOLD", "2"))
THREADS_ANGER_CRITICISM_THRESHOLD_PCT = float(os.getenv("THREADS_ANGER_CRITICISM_THRESHOLD_PCT", "25.0"))

# Database & Storage
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
TEMP_VOICE_DIR = BASE_DIR / "temp_voice"
DB_PATH = DATA_DIR / "zura.db"
