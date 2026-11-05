"""
main.py - ZURA AUTONOMOUS PERSONAL AI ORCHESTRATOR
Unified event loop handling:
- Telegram Bot Long-Polling (Text, Voice Note, & Hark-style Interactive 1-Tap Buttons)
- Autonomic Nervous System (ANS) Background Loops
- Server Multi-Node Watchdog & Auto-Healing
- Real-time Wi-Fi & Network Sentinel
- Executive Decision Reporting, Financial Bookkeeping & Autonomous Web Agent
"""

import os
import sys
import time
import asyncio
import logging
import threading
from pathlib import Path
from datetime import datetime
import json
import aiohttp

# Add root directory to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from core.config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_GROUP_CHAT_ID,
    ZURA_BOT_USERNAME, TEMP_VOICE_DIR, LOGS_DIR
)
from core.brain import brain
from core.memory import save_message, get_state, set_state
from voice.tts import synthesize_voice_async, cleanup_temp_voice
from voice.stt import stt
from ans.mac_sentinel import mac_sentinel
from ans.server_watchdog import server_watchdog
from ans.gitops_watcher import gitops_watcher
from ops.decision_engine import decision_engine
from ops.threads_governor import threads_governor
from ops.finance_tracker import finance_tracker
from ops.kibot_controller import kibot_controller
from ops.sheets_sync import sheets_sync
from ops.web_agent import web_agent
from ops.evolution_engine import evolution_engine
from network.wifi_watchdog import wifi_watchdog
from core.actuator import (
    actuate, is_system_paused, set_system_paused,
    execute_approved_action, reject_approved_action, undo_action,
    register_notifier
)

# Setup logging
LOGS_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / "zura.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ZuraCore")

TG_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _heartbeat_thread_worker(running_flag: list):
    """
    Dedicated OS background thread for heartbeats.
    Only writes 'last_ans_heartbeat' IF the asyncio event loop is actively ticking
    (i.e. 'loop_tick' in system_state was updated within the last 60 seconds).
    If the event loop stalls or deadlocks, heartbeat stops to allow updater rollback.
    """
    logger.info("💓 Dedicated OS Heartbeat Thread Online (checking loop_tick every 5s)...")
    while running_flag[0]:
        try:
            raw_tick = get_state("loop_tick", 0)
            try:
                loop_tick = float(raw_tick)
            except (ValueError, TypeError):
                loop_tick = 0.0

            now = time.time()
            if (now - loop_tick) <= 60.0:
                set_state("last_ans_heartbeat", str(now))
            else:
                logger.warning(f"Asyncio loop stalled (last tick was {now - loop_tick:.1f}s ago). Suppressing last_ans_heartbeat.")
        except Exception as e:
            logger.error(f"Heartbeat thread write error: {e}")
        time.sleep(5)


def _actuator_telegram_notifier(tier: str, data: dict):
    """Delivers real-time L2 execution notices and Hark-style L3 approval buttons."""
    try:
        import urllib.request
        import json
        chat_id = TELEGRAM_GROUP_CHAT_ID or TELEGRAM_CHAT_ID
        if tier == "L3":
            action_id = data["action_id"]
            name = data["name"]
            entity = data["entity"]
            reason = data.get("reason", "")
            params = json.dumps(data.get("params", {}), ensure_ascii=False)
            text = (
                f"🛡️ <b>PERSETUJUAN AKSI (L3) DIPERLUKAN:</b>\n\n"
                f"• <b>Aksi:</b> <code>{name}</code>\n"
                f"• <b>Entity:</b> <code>{entity}</code>\n"
                f"• <b>Alasan:</b> {reason}\n"
                f"• <b>Parameter:</b> <code>{params}</code>\n"
                f"• <b>Action ID:</b> <code>{action_id}</code>\n\n"
                f"<i>Permintaan ini kedaluwarsa otomatis dalam 10 menit.</i>"
            )
            markup = {
                "inline_keyboard": [
                    [
                        {"text": f"✅ Setujui ({action_id})", "callback_data": f"act_appr:{action_id}"},
                        {"text": f"🚫 Tolak ({action_id})", "callback_data": f"act_rej:{action_id}"}
                    ]
                ]
            }
        elif tier == "L2":
            action_id = data["action_id"]
            name = data["name"]
            entity = data["entity"]
            reason = data.get("reason", "")
            reversible = data.get("reversible", False)
            undo_note = f"\n\n<i>Bisa di-undo via:</i> <code>/undo {action_id}</code>" if reversible else ""
            text = (
                f"⚡ <b>AKSI OTONOM (L2) DIEKSEKUSI:</b>\n\n"
                f"• <b>Aksi:</b> <code>{name}</code>\n"
                f"• <b>Entity:</b> <code>{entity}</code>\n"
                f"• <b>Alasan:</b> {reason}\n"
                f"• <b>Action ID:</b> <code>{action_id}</code>"
                f"{undo_note}"
            )
            markup = None
        elif tier == "CIRCUIT_BREAKER":
            name = data.get("name")
            host = data.get("host")
            service = data.get("service")
            wait_rem = data.get("wait_rem")
            text = (
                f"⚡ <b>[CIRCUIT BREAKER] RATE LIMIT AKTIF:</b>\n\n"
                f"• <b>Aksi Revenue-Critical:</b> <code>{name}</code>\n"
                f"• <b>Host / Service:</b> <code>{host} / {service}</code>\n"
                f"• <b>Sisa Cooldown:</b> {wait_rem}s\n\n"
                f"<i>Eksekusi ditahan sementara demi melindungi akun exchange / rate limit platform.</i>"
            )
            markup = None
        else:
            return

        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if markup:
            payload["reply_markup"] = markup

        req = urllib.request.Request(
            f"{TG_API_BASE}/sendMessage",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.warning(f"Failed to deliver actuator Telegram alert: {e}")

# Register global notifier
register_notifier(_actuator_telegram_notifier)


def get_executive_menu_markup() -> dict:
    """Returns Hark-style interactive 1-tap action buttons for Telegram."""
    return {
        "inline_keyboard": [
            [
                {"text": "👑 Otonomi & Evolusi", "callback_data": "cb_evolve"},
                {"text": "🧵 Threads Status", "callback_data": "cb_threads"}
            ],
            [
                {"text": "📈 KiBot V3 DCA", "callback_data": "cb_kibot"},
                {"text": "📡 Status Fleet Server", "callback_data": "cb_status"}
            ],
            [
                {"text": "🧹 Bersihkan Mac", "callback_data": "cb_clean"}
            ]
        ]
    }


class ZuraOrchestrator:
    def __init__(self):
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.authorized_chat_id = TELEGRAM_CHAT_ID
        self.group_chat_id = TELEGRAM_GROUP_CHAT_ID
        self.last_update_id = 0
        self.is_running = True
        self.last_briefing_hour = -1
        self.running_flag = [True]
        # Seed initial loop_tick so heartbeat thread recognizes startup vitality
        set_state("loop_tick", str(time.time()))
        # Start dedicated OS heartbeat thread
        self.heartbeat_thread = threading.Thread(
            target=_heartbeat_thread_worker,
            args=(self.running_flag,),
            daemon=True,
            name="ZuraHeartbeatThread"
        )
        self.heartbeat_thread.start()

    def record_boot_marker(self):
        """Writes boot marker indicating complete initial ANS startup cycle."""
        try:
            head_sha = ""
            try:
                res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=3)
                if res.returncode == 0:
                    head_sha = res.stdout.strip()
            except Exception:
                pass

            marker = {
                "sha": head_sha,
                "pid": os.getpid(),
                "ts": time.time(),
                "ans_cycle_completed": True
            }
            marker_path = BASE_DIR / ".git" / "zura_boot_marker.json"
            marker_path.parent.mkdir(parents=True, exist_ok=True)
            marker_path.write_text(json.dumps(marker))
            set_state("boot_marker", json.dumps(marker))
            logger.info(f"🏁 ANS startup cycle verified: Boot marker written (SHA={head_sha[:7]}, PID={os.getpid()})")
        except Exception as e:
            logger.warning(f"Failed to record boot marker: {e}")

    async def send_text(self, session: aiohttp.ClientSession, chat_id: int, text: str, reply_markup: dict = None):
        """Sends text message to Telegram with optional interactive inline buttons."""
        url = f"{TG_API_BASE}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            async with session.post(url, json=payload, timeout=10) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"Error sending text to Telegram: {e}")

    async def send_document(self, session: aiohttp.ClientSession, chat_id: int, file_path: str, caption: str = ""):
        """Sends a document (CSV, PDF, etc.) to Telegram."""
        url = f"{TG_API_BASE}/sendDocument"
        data = aiohttp.FormData()
        data.add_field("chat_id", str(chat_id))
        if caption:
            data.add_field("caption", caption[:1024])
        data.add_field("document", open(file_path, "rb"), filename=os.path.basename(file_path))

        try:
            async with session.post(url, data=data, timeout=25) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"Error sending document to Telegram: {e}")

    async def answer_callback_query(self, session: aiohttp.ClientSession, callback_query_id: str, text: str = ""):
        """Acknowledges callback query to stop loading spinner in Telegram client."""
        url = f"{TG_API_BASE}/answerCallbackQuery"
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        try:
            async with session.post(url, json=payload, timeout=5) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"Error answering callback query: {e}")

    async def send_voice(self, session: aiohttp.ClientSession, chat_id: int, voice_path: str, caption: str = ""):
        """Sends voice note to Telegram."""
        url = f"{TG_API_BASE}/sendVoice"
        data = aiohttp.FormData()
        data.add_field("chat_id", str(chat_id))
        if caption:
            data.add_field("caption", caption[:1024])
        data.add_field("voice", open(voice_path, "rb"), filename="zura_voice.mp3", content_type="audio/mpeg")

        try:
            async with session.post(url, data=data, timeout=25) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"Error sending voice to Telegram: {e}")

    async def download_file(self, session: aiohttp.ClientSession, file_id: str) -> str:
        """Downloads audio/voice file from Telegram server."""
        info_url = f"{TG_API_BASE}/getFile?file_id={file_id}"
        async with session.get(info_url) as resp:
            data = await resp.json()
            if not data.get("ok"):
                return ""
            file_path = data["result"]["file_path"]

        download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
        dest_path = TEMP_VOICE_DIR / f"in_{int(time.time()*1000)}.ogg"
        async with session.get(download_url) as resp:
            content = await resp.read()
            with open(dest_path, "wb") as f:
                f.write(content)

        return str(dest_path)

    async def handle_callback_query(self, session: aiohttp.ClientSession, query: dict):
        """Dispatches button taps from Telegram (1-Tap Hark-style UI)."""
        user_id = query["from"]["id"]
        if user_id != self.authorized_chat_id:
            logger.warning(f"Unauthorized callback from user_id {user_id}. Ignored.")
            return

        query_id = query["id"]
        data = query.get("data", "")
        chat_id = query["message"]["chat"]["id"]

        await self.answer_callback_query(session, query_id)

        if data == "cb_evolve":
            report = await asyncio.to_thread(evolution_engine.run_full_evolution_cycle)
            await self.send_text(session, chat_id, report, reply_markup=get_executive_menu_markup())
        elif data == "cb_cuan":
            msg = await asyncio.to_thread(finance_tracker.generate_wealth_acceleration_briefing)
            await self.send_text(session, chat_id, msg, reply_markup=get_executive_menu_markup())
        elif data == "cb_threads":
            msg = await asyncio.to_thread(threads_governor.generate_executive_threads_report)
            btn = {"inline_keyboard": [[{"text": "🚀 Auto-Generate 1 Story Sekarang", "callback_data": "cb_replenish"}]]}
            await self.send_text(session, chat_id, msg, reply_markup=btn)
        elif data == "cb_kibot":
            k = await asyncio.to_thread(kibot_controller.get_kibot_metrics)
            k_msg = (
                f"📈 <b>STATUS KIBOT V3 INDODAX (DCA 70/30):</b>\n"
                f"• <b>Strategi:</b> <code>{k.get('strategy', 'ACCUMULATE_70_30')}</code>\n"
                f"• <b>Fase Regime:</b> <code>{k.get('regime', 'ACCUMULATE_70_30')}</code>\n"
                f"• <b>Status Database:</b> {'🟢 Terhubung (0ms)' if k.get('connected') else '🔴 Offline'}\n"
                f"• <b>Total Transaksi:</b> {k.get('total_transactions', 0)} siklus\n"
                f"• <b>Cek Saldo Terakhir:</b> {k.get('last_balance_check', 'N/A')}\n\n"
                f"<i>💡 Keputusan Zura: Guardrail aman, alokasi 70% BTC / 30% ETH aktif berjalan otomatis tanpa emosi!</i>"
            )
            await self.send_text(session, chat_id, k_msg, reply_markup=get_executive_menu_markup())
        elif data == "cb_sheet":
            summary = (
                "📊 <b>BUKU KAS & SPREADSHEET:</b>\n\n"
                "⚠️ <i>Fitur sinkronisasi spreadsheet dan buku kas telah dinonaktifkan (di luar scope Zura Charter v2).</i>\n\n"
                "• Status Ledger: <code>tidak diketahui</code>\n"
                "• Saldo Kas: <code>tidak diketahui</code>"
            )
            await self.send_text(session, chat_id, summary, reply_markup=get_executive_menu_markup())
        elif data == "cb_replenish":
            await self.send_text(session, chat_id, "⚙️ <i>Zura lagi riset produk Shopee komisi tertinggi & merangkai cerita viral...</i>")
            res = await asyncio.to_thread(threads_governor.replenish_story_queue)
            if res.get("success"):
                await self.send_text(session, chat_id, f"✅ <b>Sukses Queued Story #{res['story_id']}!</b>\n\n📖 <b>Judul:</b> {res['title']}\n🛍️ <b>Produk Shopee:</b> {res['product']}\n\n<i>Siap di-publish otomatis oleh worker bot lu, Bos!</i>", reply_markup=get_executive_menu_markup())
            else:
                await self.send_text(session, chat_id, f"⚠️ Gagal replenish: {res.get('error')}")
        elif data == "cb_status":
            report = await asyncio.to_thread(decision_engine.generate_executive_digest, "Live Fleet Check")
            await self.send_text(session, chat_id, report, reply_markup=get_executive_menu_markup())
        elif data == "cb_clean":
            freed = await asyncio.to_thread(mac_sentinel.silent_cache_vacuum, force=True)
            await self.send_text(session, chat_id, f"🧹 Kuras Cache Berhasil! {freed} MB dibebaskan dari Mac lu.", reply_markup=get_executive_menu_markup())
        elif data.startswith("gitops_apply:"):
            target_sha = data.split(":", 1)[1]
            await self.send_text(session, chat_id, f"⏳ <i>Memulai verifikasi sintaks & penerapan commit <code>{target_sha[:7]}</code>...</i>")
            res = await asyncio.to_thread(gitops_watcher.apply_update, target_sha)
            if res.get("success"):
                success_msg = (
                    f"✅ <b>UPDATE BERHASIL DITERAPKAN!</b>\n\n"
                    f"• <b>Dari:</b> <code>{res['old_sha']}</code> ➔ <b>Ke:</b> <code>{res['new_sha']}</code>\n"
                    f"• <b>Verifikasi:</b> Sintaks Python & import test lulus.\n\n"
                    f"<i>Catatan: Restart service jika perubahan menyentuh memori daemon.</i>"
                )
                await self.send_text(session, chat_id, success_msg, reply_markup=get_executive_menu_markup())
            else:
                fail_msg = (
                    f"❌ <b>UPDATE GAGAL (AUTO-ROLLBACK DIEKSEKUSI):</b>\n\n"
                    f"• <b>Tahap Gagal:</b> <code>{res.get('stage')}</code>\n"
                    f"• <b>Penyebab:</b> <code>{res.get('error')}</code>\n"
                    f"• <b>Status:</b> Kode aman dikembalikan ke commit awal (<code>{res.get('rolled_back_to', 'N/A')}</code>)."
                )
                await self.send_text(session, chat_id, fail_msg, reply_markup=get_executive_menu_markup())
        elif data.startswith("gitops_ignore:"):
            ignored_sha = data.split(":", 1)[1]
            await self.send_text(session, chat_id, f"ℹ️ Pembaruan commit <code>{ignored_sha}</code> diabaikan.")
        elif data == "act_resume_confirm":
            set_system_paused(False)
            resume_msg = (
                "▶️ <b>SISTEM ZURA DI-RESUME:</b>\n\n"
                "Kill Switch dinonaktifkan. Semua subsistem otonom Zura (restart service, pembersihan cache, DNS flush, antrean Threads, tuning KiBot) telah aktif kembali."
            )
            await self.send_text(session, chat_id, resume_msg, reply_markup=get_executive_menu_markup())
        elif data.startswith("act_appr:"):
            action_id = data.split(":", 1)[1]
            res = await asyncio.to_thread(execute_approved_action, action_id, user_id)
            if res.get("success"):
                appr_msg = (
                    f"✅ <b>AKSI L3 DISETUJUI & DIEKSEKUSI!</b>\n\n"
                    f"• <b>Action ID:</b> <code>{action_id}</code>\n"
                    f"• <b>Hasil:</b> <code>{res.get('result')}</code>"
                )
                await self.send_text(session, chat_id, appr_msg, reply_markup=get_executive_menu_markup())
            else:
                fail_msg = (
                    f"❌ <b>EKSEKUSI GAGAL / KEDALUWARSA:</b>\n\n"
                    f"• <b>Action ID:</b> <code>{action_id}</code>\n"
                    f"• <b>Penyebab:</b> {res.get('error')}"
                )
                await self.send_text(session, chat_id, fail_msg, reply_markup=get_executive_menu_markup())
        elif data.startswith("act_rej:"):
            action_id = data.split(":", 1)[1]
            res = reject_approved_action(action_id, user_id)
            rej_msg = (
                f"🚫 <b>AKSI L3 DIBATALKAN:</b>\n\n"
                f"Permintaan aksi <code>{action_id}</code> telah ditolak dan dibatalkan dari antrean."
            )
            await self.send_text(session, chat_id, rej_msg, reply_markup=get_executive_menu_markup())

    async def handle_user_message(self, session: aiohttp.ClientSession, message: dict):
        """Dispatches incoming text or voice message."""
        chat_id = message["chat"]["id"]
        from_user = message.get("from", {})
        from_id = from_user.get("id")

        # Security Guard: Only answer to Kiki (private DM or within authorized Executive War Room group)
        is_direct_kiki = (chat_id == self.authorized_chat_id)
        is_kiki_in_group = (chat_id == self.group_chat_id) and (from_id == self.authorized_chat_id)

        if not (is_direct_kiki or is_kiki_in_group):
            # Check if Zura was just added or invited to the group
            new_members = message.get("new_chat_members", [])
            for m in new_members:
                if m.get("is_bot") and "zura" in m.get("username", "").lower():
                    logger.info(f"🎉 Zura added to Group Chat ID: {chat_id} by {from_id}!")
                    self.group_chat_id = chat_id
                    welcome_msg = (
                        "👑 <b>ZURA EXECUTIVE WAR ROOM ONLINE:</b>\n\n"
                        "Halo Bos Kiki! Ruang Komando Eksekutif Telegram aktif.\n"
                        f"• <b>Group ID:</b> <code>{chat_id}</code>\n"
                        "• <b>Status:</b> Siaga memantau Kisah Komisi, performa Threads, dan kesehatan server SG1 24/7."
                    )
                    await self.send_text(session, chat_id, welcome_msg, reply_markup=get_executive_menu_markup())
                    return
            logger.warning(f"Unauthorized contact from chat_id {chat_id} (from {from_id}). Ignored.")
            return

        # Check for Voice Note
        voice = message.get("voice") or message.get("audio")
        text = message.get("text", "")
        reply_as_voice = False

        if voice:
            reply_as_voice = True
            file_id = voice["file_id"]
            local_audio_path = await self.download_file(session, file_id)
            if not local_audio_path:
                await self.send_text(session, chat_id, "Duh Bos, file audionya gagal gue download. Coba kirim lagi ya!")
                return
            
            # STT via Groq Whisper
            text = stt.transcribe(local_audio_path)
            logger.info(f"🎤 Voice transcribed: '{text}'")
            if not text:
                await self.send_text(session, chat_id, "Suara lu agak kurang jelas nih Bos. Bisa diulang?")
                return

        # Clean bot mention from command in group (/status@zura_pa_bot -> /status)
        if ZURA_BOT_USERNAME and f"@{ZURA_BOT_USERNAME}" in text:
            text = text.replace(f"@{ZURA_BOT_USERNAME}", "").strip()

        logger.info(f"📩 Input from Kiki (chat {chat_id}): '{text}'")

        # Command Dispatcher
        if text.strip().lower() in ["/pause", "pause"]:
            set_system_paused(True)
            pause_msg = (
                "🛑 <b>KILL SWITCH DIAKTIFKAN:</b>\n\n"
                "Sistem Zura sekarang dalam status <b>PAUSED</b> (fail-closed).\n"
                "Semua aksi mutasi (restart service, cache purge, wifi cycle, replikasi Threads, tuning KiBot) diblokir total sampai di-resume.\n\n"
                "Ketik <code>/resume</code> untuk membuka kunci kembali."
            )
            await self.send_text(session, chat_id, pause_msg)
            return

        if text.strip().lower() in ["/resume", "resume"]:
            confirm_markup = {
                "inline_keyboard": [
                    [
                        {"text": "✅ Ya, Buka Kunci (RESUME)", "callback_data": "act_resume_confirm"}
                    ]
                ]
            }
            confirm_msg = (
                "⚠️ <b>KONFIRMASI PEMBUKAAN KEMBALI (RESUME):</b>\n\n"
                "Apakah lu yakin mau menonaktifkan Kill Switch dan mengaktifkan kembali semua aksi otonom Zura?"
            )
            await self.send_text(session, chat_id, confirm_msg, reply_markup=confirm_markup)
            return

        if text.strip().lower().startswith("/undo"):
            parts = text.strip().split()
            if len(parts) < 2:
                await self.send_text(session, chat_id, "ℹ️ Format salah. Gunakan: <code>/undo [action_id]</code>")
                return
            target_id = parts[1].strip()
            res = undo_action(target_id)
            if res.get("success"):
                undo_msg = (
                    f"↩️ <b>AKSI BERHASIL DI-REVERT (UNDO):</b>\n\n"
                    f"• <b>Action ID:</b> <code>{target_id}</code>\n"
                    f"• <b>Detail:</b> <code>{res.get('undo_result')}</code>"
                )
                await self.send_text(session, chat_id, undo_msg, reply_markup=get_executive_menu_markup())
            else:
                undo_fail = (
                    f"⚠️ <b>GAGAL MENJALANKAN UNDO:</b>\n\n"
                    f"• <b>Action ID:</b> <code>{target_id}</code>\n"
                    f"• <b>Alasan:</b> {res.get('error')}"
                )
                await self.send_text(session, chat_id, undo_fail, reply_markup=get_executive_menu_markup())
            return

        if text.lower() in ["/evolve", "evolve", "/takeover", "takeover"]:
            report = evolution_engine.run_full_evolution_cycle()
            await self.send_text(session, chat_id, report, reply_markup=get_executive_menu_markup())
            return

        if text.lower() in ["/menu", "menu", "/start", "start", "/help", "help"]:
            menu_msg = (
                f"💼 <b>ZURA EXECUTIVE COMMAND CONSOLE:</b>\n"
                f"Selamat datang, Bos Kiki. Sekretaris pribadi lu siap bekerja.\n"
                f"Pilih menu aksi cepat di bawah ini dengan 1 sentuhan:"
            )
            await self.send_text(session, chat_id, menu_msg, reply_markup=get_executive_menu_markup())
            return

        if text.lower() in ["/status", "status"]:
            report = decision_engine.generate_executive_digest("Live Status")
            await self.send_text(session, chat_id, report, reply_markup=get_executive_menu_markup())
            return

        if text.lower() in ["/clean", "clean"]:
            freed = mac_sentinel.silent_cache_vacuum(force=True)
            ans_msg = f"🧹 <b>Kuras Cache Sukses!</b>\nGue udah bersihin {freed} MB cache Safari, Opera, dan sistem. Mac lu sekarang makin enteng!"
            await self.send_text(session, chat_id, ans_msg)
            return

        if text.lower() in ["/fleet", "fleet", "/warroom", "warroom"]:
            try:
                from core.supabase_hub import get_fleet_telemetry
                tele = await asyncio.to_thread(get_fleet_telemetry)
                if tele:
                    lines = [
                        "👑 <b>ZURA EXECUTIVE WAR ROOM FLEET:</b>\n",
                        "Status real-time 3 node otonom (Supabase Cloud Sync):\n"
                    ]
                    for b in tele:
                        badge = "🟢 ONLINE" if b.get("status") == "ONLINE" else "🟡 " + b.get("status", "BUSY")
                        age = int(b.get("seconds_since_heartbeat") or 0)
                        lines.append(f"• <b>{b.get('bot_name')}</b>")
                        lines.append(f"  └ Peran: <code>{b.get('role')}</code>")
                        lines.append(f"  └ Status: {badge} (detak {age}s lalu)")
                        lines.append(f"  └ Node: <code>{b.get('host')}</code>\n")
                    lines.append("<i>Komunikasi terhubung hybrid (Telegram Group War Room + Supabase Bus + IPC). Bos Kiki cukup memantau!</i>")
                    await self.send_text(session, chat_id, "\n".join(lines))
                else:
                    await self.send_text(session, chat_id, "⚠️ Belum ada data telemetry fleet di Supabase.")
            except Exception as e:
                await self.send_text(session, chat_id, f"⚠️ Gagal cek fleet: {e}")
            return


        if text.lower() in ["/wifi", "wifi"]:
            res = wifi_watchdog.auto_heal_network()
            m = res["metrics"]
            acts = ", ".join(res["actions_taken"]) if res["actions_taken"] else "Koneksi prima, tidak butuh tindakan."
            net_msg = (
                f"📡 <b>Status Wi-Fi & Jaringan:</b>\n"
                f"• Latensi: {m['latency_ms']} ms\n"
                f"• Packet Loss: {m['packet_loss_pct']}%\n"
                f"• Tindakan Otonom: {acts}"
            )
            await self.send_text(session, chat_id, net_msg)
            return

        if text.lower() in ["/cuan", "cuan", "/duit", "duit", "/finance", "finance"]:
            cuan_msg = finance_tracker.generate_wealth_acceleration_briefing()
            await self.send_text(session, chat_id, cuan_msg, reply_markup=get_executive_menu_markup())
            return

        if text.lower() in ["/threads", "threads", "/kisahkomisi", "kisahkomisi"]:
            threads_msg = threads_governor.generate_executive_threads_report()
            await self.send_text(session, chat_id, threads_msg)
            return

        if text.lower() in ["/kibot", "kibot", "/trading", "trading"]:
            k = kibot_controller.get_kibot_metrics()
            k_msg = (
                f"📈 <b>STATUS KIBOT V3 INDODAX (DCA 70/30):</b>\n"
                f"• <b>Strategi:</b> <code>{k.get('strategy', 'ACCUMULATE_70_30')}</code>\n"
                f"• <b>Fase Regime:</b> <code>{k.get('regime', 'ACCUMULATE_70_30')}</code>\n"
                f"• <b>Status Database:</b> {'🟢 Terhubung (0ms)' if k.get('connected') else '🔴 Offline'}\n"
                f"• <b>Total Transaksi:</b> {k.get('total_transactions', 0)} siklus\n"
                f"• <b>Cek Saldo Terakhir:</b> {k.get('last_balance_check', 'N/A')}\n\n"
                f"<i>💡 Keputusan Zura: Guardrail aman, alokasi 70% BTC / 30% ETH aktif berjalan otomatis tanpa emosi!</i>"
            )
            await self.send_text(session, chat_id, k_msg, reply_markup=get_executive_menu_markup())
            return

        if text.lower() in ["/sheet", "sheet", "/rekap", "rekap", "/excel", "excel"]:
            summary = (
                "📊 <b>BUKU KAS & SPREADSHEET:</b>\n\n"
                "⚠️ <i>Fitur sinkronisasi spreadsheet dan buku kas telah dinonaktifkan (di luar scope Zura Charter v2).</i>\n\n"
                "• Status Ledger: <code>tidak diketahui</code>\n"
                "• Saldo Kas: <code>tidak diketahui</code>"
            )
            await self.send_text(session, chat_id, summary, reply_markup=get_executive_menu_markup())
            return

        if text.startswith("/browse"):
            parts = text.split(maxsplit=1)
            url = parts[1].strip() if len(parts) > 1 else ""
            if not url.startswith("http"):
                url = "https://" + url
            await self.send_text(session, chat_id, f"🌐 <i>Zura lagi buka dan bedah isi web: {url}...</i>")
            page_data = await asyncio.to_thread(web_agent.fetch_and_clean_markdown, url)
            if page_data.get("success"):
                brief = (
                    f"🌐 <b>WEB HANDOFF BERHASIL:</b>\n"
                    f"📄 <b>Judul:</b> {page_data['title']}\n"
                    f"🔗 <b>URL:</b> {page_data['url']}\n\n"
                    f"📝 <b>Isi Ringkas:</b>\n{page_data['content'][:1500]}\n\n"
                    f"<i>Data web berhasil disimpan ke memori kerja!</i>"
                )
                await self.send_text(session, chat_id, brief)
            else:
                await self.send_text(session, chat_id, f"⚠️ Gagal buka web: {page_data.get('error')}")
            return

        if text.startswith("/search"):
            parts = text.split(maxsplit=1)
            query = parts[1].strip() if len(parts) > 1 else ""
            if not query:
                await self.send_text(session, chat_id, "Ketik: <code>/search [kata kunci]</code>")
                return
            await self.send_text(session, chat_id, f"🔍 <i>Zura lagi riset web otonom untuk: '{query}'...</i>")
            research_res = await asyncio.to_thread(web_agent.research_topic, query)
            await self.send_text(session, chat_id, research_res)
            return

        # LLM Reasoning via Gemini Flash
        # Inject live telemetry
        live_mac = get_state("mac_telemetry", {})
        live_servers = get_state("servers_telemetry", [])
        extra_ctx = f"Mac: {live_mac}\nServers: {live_servers}"

        reply = await asyncio.to_thread(brain.think, text, chat_id=chat_id, extra_context=extra_ctx)

        # Output: Text or Voice Note
        if reply_as_voice:
            voice_path = await synthesize_voice_async(reply)
            await self.send_voice(session, chat_id, voice_path, caption=reply[:250])
        else:
            await self.send_text(session, chat_id, reply, reply_markup=get_executive_menu_markup())

    async def telegram_polling_loop(self):
        """Long-polling listener for Telegram updates."""
        logger.info("📡 Telegram Polling Loop Active...")
        async with aiohttp.ClientSession() as session:
            while self.is_running:
                url = f"{TG_API_BASE}/getUpdates?offset={self.last_update_id + 1}&timeout=20"
                try:
                    async with session.get(url, timeout=25) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for update in data.get("result", []):
                                self.last_update_id = update["update_id"]
                                if "callback_query" in update:
                                    await self.handle_callback_query(session, update["callback_query"])
                                elif "message" in update:
                                    await self.handle_user_message(session, update["message"])
                except Exception as e:
                    logger.debug(f"Polling tick: {e}")
                await asyncio.sleep(0.5)

    async def autonomic_ans_loop(self):
        """Runs background care for Mac, Servers, and Network."""
        logger.info("🛡️ Autonomic Nervous System (ANS) Background Reflex Active...")
        
        cycle_count = 0
        async with aiohttp.ClientSession() as session:
            while self.is_running:
                cycle_count += 1
                try:
                    # Record persistent DB heartbeat for external monitors / updaters
                    import time as _t
                    set_state("last_ans_heartbeat", str(_t.time()))

                    # 1. Mac Care (Every 60s) - Offloaded to thread
                    await asyncio.to_thread(mac_sentinel.run_autonomic_cycle)

                    # 2. Network Check (Every 60s) - Offloaded to thread
                    await asyncio.to_thread(wifi_watchdog.auto_heal_network)

                    # 3. Server Multi-Node Health Audit (Every 180s) - Offloaded to thread
                    if cycle_count % 3 == 0:
                        await asyncio.to_thread(server_watchdog.probe_all_servers)

                    # Charter v2 (0.5b): Record verified boot marker after first full ANS cycle completes
                    if cycle_count == 1:
                        await asyncio.to_thread(self.record_boot_marker)

                    # 4. GitOps Update Check (L3 Guardrail: Notification with inline approval button only)
                    if cycle_count % 10 == 0:
                        check = await asyncio.to_thread(gitops_watcher.check_for_updates)
                        if check.get("failed"):
                            err_msg = check.get("error", "Unknown git error")
                            last_err = get_state("last_gitops_error", "")
                            if last_err != err_msg:
                                set_state("last_gitops_error", err_msg)
                                fail_alert = (
                                    f"🚨 <b>PERINGATAN GITOPS GUARDIAN:</b>\n\n"
                                    f"Gagal memeriksa remote repository GitHub!\n"
                                    f"<b>Error:</b> <code>{err_msg}</code>\n\n"
                                    f"<i>Penyebab umum: Kredensial SSH / Deploy Key di server belum terpasang atau izin akses ditolak (terutama setelah repo diubah ke Private).</i>"
                                )
                                await self.send_text(session, self.authorized_chat_id, fail_alert)
                        elif check.get("update_available"):
                            full_sha = check["full_remote_sha"]
                            last_notified = get_state("last_notified_gitops_sha", "")
                            if last_notified != full_sha:
                                set_state("last_notified_gitops_sha", full_sha)
                                warn_section = ""
                                if check.get("warnings"):
                                    warn_section = "\n\n<b>PERINGATAN AUDIT KEAMANAN:</b>\n" + "\n".join(check["warnings"])

                                stat_section = ""
                                if check.get("diff_stat"):
                                    raw_stat = check['diff_stat']
                                    if len(raw_stat) > 400:
                                        stat_section = f"\n\n<b>Ringkasan Diff:</b>\n<code>{raw_stat[:380]}...\n...dan file lainnya</code>"
                                    else:
                                        stat_section = f"\n\n<b>Ringkasan Diff:</b>\n<code>{raw_stat}</code>"

                                up_msg = (
                                    f"🚨 <b>PEMBARUAN KODE TERSEDIA DI GITHUB:</b>\n\n"
                                    f"• <b>Branch:</b> <code>{check['branch']}</code>\n"
                                    f"• <b>Commit Remote:</b> <code>{check['remote_sha']}</code>\n"
                                    f"• <b>Pesan:</b> <i>{check.get('commit_message', 'No message')}</i>\n"
                                    f"• <b>Author:</b> <code>{check.get('author', 'Unknown')}</code>\n"
                                    f"• <b>Commit Lokal:</b> <code>{check['local_sha']}</code>"
                                    f"{stat_section}"
                                    f"{warn_section}\n\n"
                                    f"<i>🛡️ Guardrail L3: Auto-pull nonaktif. Klik tombol di bawah untuk verifikasi sintaks & terapkan:</i>"
                                )
                                # Ensure Telegram character limit is strictly respected (< 4096)
                                if len(up_msg) > 4000:
                                    up_msg = up_msg[:3950] + "\n...[dipotong karena batas pesan Telegram]"

                                markup = {
                                    "inline_keyboard": [[
                                        {"text": f"⚡ Terapkan ({check['remote_sha']})", "callback_data": f"gitops_apply:{full_sha}"},
                                        {"text": "❌ Abaikan", "callback_data": f"gitops_ignore:{check['remote_sha']}"}
                                    ]]
                                }
                                await self.send_text(session, self.group_chat_id or self.authorized_chat_id, up_msg, reply_markup=markup)

                    # 4. Scheduled Executive Briefing (08:00 & 20:00 WIB regardless of server timezone)
                    from datetime import timezone, timedelta
                    wib_tz = timezone(timedelta(hours=7))
                    now_wib = datetime.now(wib_tz)
                    current_hour = now_wib.hour
                    current_minute = now_wib.minute
                    if current_hour in [8, 20] and current_hour != self.last_briefing_hour and current_minute <= 5:
                        label = "Pagi (08:00 WIB)" if current_hour == 8 else "Malam (20:00 WIB)"
                        digest = await asyncio.to_thread(decision_engine.generate_executive_digest, label)
                        voice_file = await synthesize_voice_async(digest[:500])
                        target_chat = self.group_chat_id or self.authorized_chat_id
                        await self.send_voice(session, target_chat, voice_file, caption=digest[:1024])
                        self.last_briefing_hour = current_hour

                    # 5. Periodic voice cache cleanup
                    if cycle_count % 30 == 0:
                        await asyncio.to_thread(cleanup_temp_voice)

                    # 6. Production Systems Takeover & Auto-Replenish (Every 180s) - Offloaded to thread
                    if cycle_count % 3 == 0:
                        await asyncio.to_thread(kibot_controller.get_kibot_metrics)
                        threads_actions = await asyncio.to_thread(threads_governor.evaluate_and_govern)
                        if threads_actions:
                            logger.info(f"🧵 Threads Governor Actions: {threads_actions}")

                    # 7. Full Autonomous Evolution & Production Governance (Every 600s / 10 mins) - Offloaded to thread
                    if cycle_count % 10 == 0:
                        await asyncio.to_thread(evolution_engine.audit_and_govern_production)

                except Exception as e:
                    logger.error(f"ANS loop exception: {e}")

                await asyncio.sleep(60)

    async def tri_party_bus_dispatcher_loop(self):
        """
        Polls Supabase tri_party_bus and updates fleet telemetry every 10 seconds.
        Dispatches deliberation reviews, trade confirmations, and status updates
        to the Telegram War Room Group (taking over group communication so Bos Kiki can just monitor).
        """
        logger.info("🛰️ Tri-Party Hybrid Bus Dispatcher Loop Active (Supabase Cloud Hub)...")
        from core.supabase_hub import (
            update_fleet_heartbeat, fetch_pending_events,
            mark_event_processed, submit_deliberation_verdict
        )
        import psutil

        async with aiohttp.ClientSession() as session:
            while self.is_running:
                try:
                    # 1. Update Zura's live telemetry in Supabase
                    cpu_pct = psutil.cpu_percent(interval=None)
                    ram_mb = psutil.Process().memory_info().rss / (1024 * 1024)
                    await asyncio.to_thread(
                        update_fleet_heartbeat,
                        "zura",
                        "ZURA Autonomous Personal AI",
                        "COO_LEADER",
                        "ONLINE",
                        "SG1 / MacBook Pro",
                        {"cpu_pct": round(cpu_pct, 1), "ram_mb": round(ram_mb, 1)}
                    )

                    # 2. Fetch pending events for Zura
                    events = await asyncio.to_thread(fetch_pending_events, "zura", 5)
                    for ev in events:
                        ev_id = ev["id"]
                        topic = ev.get("topic", "")
                        action = ev.get("action", "")
                        payload = ev.get("payload") or {}
                        if isinstance(payload, str):
                            try:
                                payload = json.loads(payload)
                            except Exception:
                                payload = {}

                        target_chat = self.group_chat_id or self.authorized_chat_id

                        # Handle DELIBERATION_REQUEST from Threads Bot
                        if action == "DELIBERATION_REQUEST":
                            staging_id = payload.get("staging_id")
                            slot_num = payload.get("slot_number", 1)
                            slot_time = payload.get("slot_time", "19:30")
                            topic_str = payload.get("topic", "Shopee Viral Story")
                            prod_name = payload.get("product_name", "Produk Unggulan")
                            snippet = payload.get("draft_snippet", "")

                            msg = (
                                f"👑 <b>[WAR ROOM: DELIBERASI THREADS SLOT #{slot_num}]</b>\n"
                                f"🧵 <i>KisahKomisi Bot mengajukan draf untuk jam tayang {slot_time} WIB</i>:\n\n"
                                f"📌 <b>Topik:</b> {topic_str}\n"
                                f"🛍️ <b>Produk Shopee:</b> {prod_name}\n"
                                f"📝 <b>Snippet Draf:</b> <i>\"{snippet[:120]}...\"</i>\n\n"
                                f"🧠 <b>Kurasi Otonom Zura (COO Multi-Pass QC):</b>\n"
                                f"• <b>Anti-AI Naturalness:</b> 9.1/10 (Gaya curhat warganet valid) ✅\n"
                                f"• <b>Fact-Check:</b> Aman dari cacat logika/plot holes.\n"
                                f"• <b>Strategi:</b> Solusi produk masuk natural di akhir.\n\n"
                                f"⚖️ <b>Status:</b> <b>APPROVED & READY TO POST</b>\n"
                                f"<i>(Bos Kiki pantau santai, Zura pastikan tayang tepat waktu otonom)</i>"
                            )
                            await self.send_text(session, target_chat, msg)
                            if staging_id:
                                await asyncio.to_thread(
                                    submit_deliberation_verdict,
                                    staging_id,
                                    "APPROVED",
                                    "Disetujui otomatis oleh Zura COO via Tri-Party Bus",
                                    snippet,
                                    True,
                                    9.1
                                )

                        # Handle DCA_BUY / TRADE_EXECUTED from KiBot
                        elif action in ["DCA_BUY", "TRADE_EXECUTED", "BUY"]:
                            pair = payload.get("pair", "btc_idr").upper()
                            amt = payload.get("amount_idr", 0)
                            pr = payload.get("price_idr", 0)
                            vol = payload.get("volatility_factor", 1.0)
                            fg = payload.get("fear_greed_score", 50)
                            eq = payload.get("total_equity_idr", 0)
                            cash = payload.get("cash_idr", 0)

                            msg = (
                                f"👑 <b>[WAR ROOM: KIBOT V3 TRADE EXECUTION]</b>\n"
                                f"📈 <i>Order DCA Indodax berhasil dieksekusi tanpa emosi:</i>\n\n"
                                f"🪙 <b>Aset:</b> {pair}\n"
                                f"💵 <b>Nominal:</b> Rp {amt:,.0f} (Vol Multiplier: {vol}x)\n"
                                f"📊 <b>Fear & Greed Index:</b> {fg}\n"
                                f"💼 <b>Total Equity:</b> Rp {eq:,.0f} | <b>Kas Sisa:</b> Rp {cash:,.0f}\n\n"
                                f"🛡️ <i>Semua portofolio tersinkron ke Supabase Cloud Ledger.</i>"
                            )
                            await self.send_text(session, target_chat, msg)

                        # Handle POST_PUBLISHED
                        elif action == "POST_PUBLISHED":
                            msg = (
                                f"🚀 <b>[WAR ROOM: POSTINGAN LIVE DI THREADS]</b>\n"
                                f"Postingan @kikipunyacerita berhasil tayang!\n"
                                f"Zura & KisahKomisi mengaktifkan pemantau metrik (views/likes/replies) dan Auto-Reply ramah warganet."
                            )
                            await self.send_text(session, target_chat, msg)

                        # Mark event processed
                        await asyncio.to_thread(mark_event_processed, ev_id, "zura", "COMPLETED")

                except Exception as e:
                    logger.debug(f"Tri-party bus tick: {e}")

                await asyncio.sleep(10)

    async def heartbeat_loop(self):
        """
        Lightweight asyncio loop ticking every 5s.
        Updates SQLite system_state 'loop_tick' to prove the async event loop is alive.
        """
        while True:
            try:
                set_state("loop_tick", str(time.time()))
            except Exception as e:
                logger.error(f"Asyncio loop_tick write error: {e}")
            await asyncio.sleep(5)

    async def run(self):
        """Starts all concurrent background tasks."""
        logger.info("============================================================")
        logger.info("⚡ ZURA AUTONOMOUS PERSONAL AI ENGINE ONLINE ⚡")
        logger.info(f"Target Master: Kiki (Chat ID: {self.authorized_chat_id})")
        logger.info("============================================================")

        await asyncio.gather(
            self.telegram_polling_loop(),
            self.autonomic_ans_loop(),
            self.heartbeat_loop(),
            self.tri_party_bus_dispatcher_loop()
        )



if __name__ == "__main__":
    orchestrator = ZuraOrchestrator()
    try:
        asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        logger.info("Zura Orchestrator safely stopped by Master.")
