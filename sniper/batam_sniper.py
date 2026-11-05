"""
sniper/batam_sniper.py - Autonomous 24/7 OCI Batam Ampere A1 Hunter
Runs on Server 1 (OCI Singapore) to relentlessly hunt for ARM VM.Standard.A1.Flex capacity.
"""

import os
import sys
import time
import random
import json
import logging
import requests
from datetime import datetime, time as dtime
from pathlib import Path

# Load environment variables from candidate locations
try:
    from dotenv import load_dotenv
    for env_candidate in [
        Path("/home/ubuntu/zura-core/.env"),
        Path("/home/ubuntu/zura-sniper/.env"),
        Path.home() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
        Path(".env")
    ]:
        if env_candidate.exists():
            load_dotenv(env_candidate)
except ImportError:
    # Manual parser if python-dotenv is not installed
    for env_candidate in [
        Path("/home/ubuntu/zura-core/.env"),
        Path("/home/ubuntu/zura-sniper/.env"),
        Path(__file__).resolve().parent.parent / ".env",
        Path(".env")
    ]:
        if env_candidate.exists():
            try:
                with open(env_candidate, "r") as ef:
                    for line in ef:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip('"').strip("'")
                            if k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("batam_sniper.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Target Configurations
COMPARTMENT_ID = os.getenv("OCI_BATAM_COMPARTMENT", "ocid1.tenancy.oc1..aaaaaaaaek3bd3hfgtqqghqhxnxbewdnulkbmvuzd53adononnor33c44p5q")
AVAILABILITY_DOMAIN = os.getenv("OCI_BATAM_AD", "tIse:AP-BATAM-1-AD-1")
SUBNET_ID = os.getenv("OCI_BATAM_SUBNET", "ocid1.subnet.oc1.ap-batam-1.aaaaaaaaftmgyr6xkep6yl2snso6yjasoi3m2a77s2kbdrsndebqujfays7q")
IMAGE_ID = os.getenv("OCI_BATAM_IMAGE", "ocid1.image.oc1.ap-batam-1.aaaaaaaapeavfbdxgxzn2nvvjlmvbr2pxan2tf5jurb734jau7o2d4n7tuuq")

# Resolve SSH authorized key
SSH_KEY = os.getenv("OCI_SSH_AUTHORIZED_KEY", "")
if not SSH_KEY:
    for key_path in [Path.home() / ".ssh/id_rsa.pub", Path.home() / ".ssh/id_ed25519.pub", Path.home() / ".ssh/authorized_keys"]:
        if key_path.exists():
            try:
                SSH_KEY = key_path.read_text().strip().splitlines()[0]
                break
            except Exception:
                pass
if not SSH_KEY:
    SSH_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFXm/CsEpcLiSl3x5sZsgrJge5ZbKfySAvaMVrFHmc5M kiki@Fikris-MacBook-Pro.local"

# Hunting Tiers - Prioritize 1 OCPU / 6GB and 2 OCPU / 12GB to stay within Free Tier regional limits
TIERS = [
    {"ocpus": 1, "memory_gb": 6,  "name": "Agile Tier (1 OCPU / 6GB RAM)"},
    {"ocpus": 2, "memory_gb": 12, "name": "Standard Tier (2 OCPU / 12GB RAM)"},
    {"ocpus": 4, "memory_gb": 24, "name": "Monster Tier (4 OCPU / 24GB RAM)"}
]


def send_telegram_alert(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logging.error(f"Failed to transmit Telegram alert: {e}")


def run_sniper():
    try:
        import oci
    except ImportError:
        logging.error("Missing 'oci' python SDK. Please run: pip install oci")
        return

    # OCI Client configuration
    config_file = os.path.expanduser("~/.oci/config")
    try:
        oci_config = oci.config.from_file(config_file, profile_name="BATAM")
        compute_client = oci.core.ComputeClient(oci_config)
    except Exception as e:
        logging.error(f"Failed to load OCI BATAM profile: {e}")
        return

    logging.info("=" * 60)
    logging.info("🎯 ZURA BATAM AMPERE A1 SNIPER ACTIVATED (24/7 DAEMON)")
    logging.info(f"Target Region: ap-batam-1 | AD: {AVAILABILITY_DOMAIN}")
    logging.info("=" * 60)

    attempts = 0
    tier_idx = 0
    consecutive_out_of_capacity = 0
    backoff = 45

    while True:
        attempts += 1
        tier = TIERS[tier_idx]
        display_name = f"Zura-Batam-A1-{int(time.time())}"

        logging.info(f"[Attempt #{attempts}] Firing sniper at {tier['name']}...")

        launch_details = oci.core.models.LaunchInstanceDetails(
            compartment_id=COMPARTMENT_ID,
            availability_domain=AVAILABILITY_DOMAIN,
            shape="VM.Standard.A1.Flex",
            shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                ocpus=tier["ocpus"],
                memory_in_gbs=tier["memory_gb"]
            ),
            create_vnic_details=oci.core.models.CreateVnicDetails(
                subnet_id=SUBNET_ID,
                assign_public_ip=True
            ),
            image_id=IMAGE_ID,
            display_name=display_name,
            metadata={"ssh_authorized_keys": SSH_KEY}
        )

        try:
            resp = compute_client.launch_instance(launch_details)
            if resp.status == 200:
                instance = resp.data
                inst_id = instance.id
                logging.info(f"🎉🎉🎉 SUCCESS! BATAM INSTANCE LAUNCHED! ID: {inst_id}")
                
                alert_msg = (
                    f"🚀 <b>BOS KIKI! ZURA BERHASIL DAPETIN SERVER BATAM!</b>\n\n"
                    f"• <b>Shape:</b> VM.Standard.A1.Flex ({tier['name']})\n"
                    f"• <b>Instance ID:</b> <code>{inst_id}</code>\n"
                    f"• <b>Total Percobaan:</b> {attempts}x\n"
                    f"• <b>Status:</b> PROVISIONING (Node ke-6 siap gabung cluster!)\n\n"
                    f"<i>Sniper Batam resmi dimatikan karena misi telah tercapai dengan sukses!</i> ⚡"
                )
                send_telegram_alert(alert_msg)
                break

        except oci.exceptions.ServiceError as e:
            if e.status == 429 or e.code == "TooManyRequests":
                logging.warning("⚠️ RATE LIMIT 429 from Oracle API. Cooling down for 90s...")
                time.sleep(90)
            elif "LimitExceeded" in str(e.code) or "limit" in str(e.message).lower() or "LimitExceeded" in str(e.message):
                logging.warning(f"⚠️ LimitExceeded ({e.code}) on {tier['name']}. Cycling to next tier immediately...")
                tier_idx = (tier_idx + 1) % len(TIERS)
                logging.info(f"🔄 Next target tier: {TIERS[tier_idx]['name']}")
                time.sleep(45)
            elif "Out of host capacity" in str(e.message) or "out of capacity" in str(e.message).lower():
                consecutive_out_of_capacity += 1
                logging.info(f"❌ OUT OF CAPACITY on {tier['name']} (streak: {consecutive_out_of_capacity})")
                
                # Dynamic Tier Cycling: Switch tier every 3 attempts if out of capacity
                if consecutive_out_of_capacity % 3 == 0:
                    tier_idx = (tier_idx + 1) % len(TIERS)
                    logging.info(f"🔄 Cycling target tier to {TIERS[tier_idx]['name']}...")
                
                # Smart Jitter Delay (40-75 seconds)
                jitter = random.randint(40, 75)
                time.sleep(jitter)
            else:
                logging.error(f"❓ OCI Error ({e.status}): {e.code} - {e.message}")
                tier_idx = (tier_idx + 1) % len(TIERS)
                time.sleep(60)

        except Exception as e:
            logging.error(f"Unhandled sniper exception: {e}")
            time.sleep(60)


if __name__ == "__main__":
    run_sniper()
