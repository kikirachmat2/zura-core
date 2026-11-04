"""
core/config.py - Zura Configuration Loader
Loads environment variables and sets path constants.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory of Personal AI
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
ZURA_BOT_USERNAME = os.getenv("ZURA_BOT_USERNAME", "zura_pa_bot")

# AI Engines
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
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

# Email & Cowork Gateway
EMAIL_IMAP_SERVER = os.getenv("EMAIL_IMAP_SERVER", "imap.gmail.com")
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "993"))

# Personal Hotspot Failover
PERSONAL_HOTSPOT_SSID = os.getenv("PERSONAL_HOTSPOT_SSID", "PersonalHotspot")
PERSONAL_HOTSPOT_PASS = os.getenv("PERSONAL_HOTSPOT_PASS", "")

# Database & Storage
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
TEMP_VOICE_DIR = BASE_DIR / "temp_voice"
DB_PATH = DATA_DIR / "zura.db"
