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
from pathlib import Path
from datetime import datetime
import aiohttp

# Add root directory to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from core.config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TEMP_VOICE_DIR, LOGS_DIR
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
from core.email_watchdog import email_watchdog

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


def get_executive_menu_markup() -> dict:
    """Returns Hark-style interactive 1-tap action buttons for Telegram."""
    return {
        "inline_keyboard": [
            [
                {"text": "👑 Otonomi & Evolusi", "callback_data": "cb_evolve"},
                {"text": "💰 Cuan & Cashflow", "callback_data": "cb_cuan"}
            ],
            [
                {"text": "🧵 Threads Status", "callback_data": "cb_threads"},
                {"text": "📈 KiBot V3 DCA", "callback_data": "cb_kibot"}
            ],
            [
                {"text": "📊 Unduh Spreadsheet", "callback_data": "cb_sheet"},
                {"text": "💳 Audit Langganan", "callback_data": "cb_subs"}
            ],
            [
                {"text": "📡 Status Fleet Server", "callback_data": "cb_status"},
                {"text": "🧹 Bersihkan Mac", "callback_data": "cb_clean"}
            ]
        ]
    }


class ZuraOrchestrator:
    def __init__(self):
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.authorized_chat_id = TELEGRAM_CHAT_ID
        self.last_update_id = 0
        self.is_running = True
        self.last_briefing_hour = -1

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
            report = evolution_engine.run_full_evolution_cycle()
            await self.send_text(session, chat_id, report, reply_markup=get_executive_menu_markup())
        elif data == "cb_cuan":
            msg = finance_tracker.generate_wealth_acceleration_briefing()
            await self.send_text(session, chat_id, msg, reply_markup=get_executive_menu_markup())
        elif data == "cb_threads":
            msg = threads_governor.generate_executive_threads_report()
            btn = {"inline_keyboard": [[{"text": "🚀 Auto-Generate 1 Story Sekarang", "callback_data": "cb_replenish"}]]}
            await self.send_text(session, chat_id, msg, reply_markup=btn)
        elif data == "cb_kibot":
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
        elif data == "cb_subs":
            subs = email_watchdog.audit_subscriptions(days=60)
            if not subs:
                await self.send_text(session, chat_id, "✨ Gak ada tagihan langganan mencurigakan dalam 60 hari terakhir, Bos!")
            else:
                sub_lines = "\n".join([f"• <b>{s['service']}</b>: {s['subject']} (~{s['cost_estimate']})" for s in subs[:8]])
                report = (
                    f"💳 <b>AUDIT LANGGANAN (SUBSCRIPTION VAMPIRE HUNTER):</b>\n\n"
                    f"{sub_lines}\n\n"
                    f"💡 <i>Zura sarankan cek layanan di atas. Stop auto-renewal yang gak ngasilin ROI!</i>"
                )
                await self.send_text(session, chat_id, report, reply_markup=get_executive_menu_markup())
        elif data == "cb_sheet":
            csv_path = sheets_sync.export_ledger_to_csv()
            summary = sheets_sync.generate_executive_spreadsheet_summary()
            await self.send_document(session, chat_id, str(csv_path), caption="📊 Buku Kas & Cuan Bos Kiki (Format CSV Excel-Ready)")
            await self.send_text(session, chat_id, summary, reply_markup=get_executive_menu_markup())
        elif data == "cb_replenish":
            await self.send_text(session, chat_id, "⚙️ <i>Zura lagi riset produk Shopee komisi tertinggi & merangkai cerita viral...</i>")
            res = threads_governor.replenish_story_queue()
            if res.get("success"):
                await self.send_text(session, chat_id, f"✅ <b>Sukses Queued Story #{res['story_id']}!</b>\n\n📖 <b>Judul:</b> {res['title']}\n🛍️ <b>Produk Shopee:</b> {res['product']}\n\n<i>Siap di-publish otomatis oleh worker bot lu, Bos!</i>", reply_markup=get_executive_menu_markup())
            else:
                await self.send_text(session, chat_id, f"⚠️ Gagal replenish: {res.get('error')}")
        elif data == "cb_status":
            report = decision_engine.generate_executive_digest("Live Fleet Check")
            await self.send_text(session, chat_id, report, reply_markup=get_executive_menu_markup())
        elif data == "cb_clean":
            freed = mac_sentinel.silent_cache_vacuum(force=True)
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

    async def handle_user_message(self, session: aiohttp.ClientSession, message: dict):
        """Dispatches incoming text or voice message."""
        chat_id = message["chat"]["id"]
        
        # Security Guard: Only answer to Kiki
        if chat_id != self.authorized_chat_id:
            logger.warning(f"Unauthorized contact from chat_id {chat_id}. Ignored.")
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

        logger.info(f"📩 Input from Kiki: '{text}'")

        # Command Dispatcher
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
            csv_path = sheets_sync.export_ledger_to_csv()
            summary = sheets_sync.generate_executive_spreadsheet_summary()
            await self.send_document(session, chat_id, str(csv_path), caption="📊 Buku Kas & Cuan Bos Kiki (Format CSV Excel-Ready)")
            await self.send_text(session, chat_id, summary, reply_markup=get_executive_menu_markup())
            return

        if text.startswith("/reply"):
            parts = text.split(maxsplit=1)
            draft_id = parts[1].strip() if len(parts) > 1 else ""
            pending = get_state("pending_email_drafts", {})
            if draft_id in pending:
                item = pending[draft_id]
                res = email_watchdog.send_reply(item["to"], item["subject"], item["draft"])
                if res.get("success"):
                    await self.send_text(session, chat_id, f"✅ <b>Email Berhasil Terkirim!</b>\n\nKe: <code>{res['recipient']}</code>\nSubjek: <b>{item['subject']}</b>\n\n<i>Zura sudah tembak via Google SMTP resmi akun lu, Bos!</i>")
                else:
                    await self.send_text(session, chat_id, f"❌ <b>Gagal Kirim Email:</b> {res.get('error')}")
            else:
                await self.send_text(session, chat_id, "⚠️ Draf email tidak ditemukan atau ID salah.")
            return

        if text.lower() in ["/subs", "subs", "/langganan", "langganan"]:
            await self.send_text(session, chat_id, "🔍 <i>Zura lagi scan email 60 hari ke belakang buat audit tagihan langganan lu...</i>")
            subs = email_watchdog.audit_subscriptions(days=60)
            if not subs:
                await self.send_text(session, chat_id, "✨ Gak ada tagihan langganan mencurigakan dalam 60 hari terakhir, Bos!")
            else:
                sub_lines = "\n".join([f"• <b>{s['service']}</b>: {s['subject']} (~{s['cost_estimate']})" for s in subs[:8]])
                report = (
                    f"💳 <b>AUDIT LANGGANAN (SUBSCRIPTION VAMPIRE HUNTER):</b>\n\n"
                    f"{sub_lines}\n\n"
                    f"💡 <i>Zura sarankan cek layanan di atas. Stop auto-renewal yang gak ngasilin ROI!</i>"
                )
                await self.send_text(session, chat_id, report, reply_markup=get_executive_menu_markup())
            return

        if text.startswith("/browse"):
            parts = text.split(maxsplit=1)
            url = parts[1].strip() if len(parts) > 1 else ""
            if not url.startswith("http"):
                url = "https://" + url
            await self.send_text(session, chat_id, f"🌐 <i>Zura lagi buka dan bedah isi web: {url}...</i>")
            page_data = web_agent.fetch_and_clean_markdown(url)
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
            research_res = web_agent.research_topic(query)
            await self.send_text(session, chat_id, research_res)
            return

        # LLM Reasoning via Gemini Flash
        # Inject live telemetry
        live_mac = get_state("mac_telemetry", {})
        live_servers = get_state("servers_telemetry", [])
        extra_ctx = f"Mac: {live_mac}\nServers: {live_servers}"

        reply = brain.think(text, chat_id=chat_id, extra_context=extra_ctx)

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
                    # 1. Mac Care (Every 60s)
                    mac_sentinel.run_autonomic_cycle()

                    # 2. Network Check (Every 60s)
                    wifi_watchdog.auto_heal_network()

                    # 3. Server Multi-Node Health Audit (Every 180s)
                    if cycle_count % 3 == 0:
                        server_watchdog.probe_all_servers()

                    # 4. GitOps Update Check (L3 Guardrail: Notification with inline approval button only)
                    if cycle_count % 10 == 0:
                        check = gitops_watcher.check_for_updates()
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
                                await self.send_text(session, self.authorized_chat_id, up_msg, reply_markup=markup)

                    # 4. Scheduled Executive Briefing (08:00 & 20:00 WIB regardless of server timezone)
                    from datetime import timezone, timedelta
                    wib_tz = timezone(timedelta(hours=7))
                    now_wib = datetime.now(wib_tz)
                    current_hour = now_wib.hour
                    current_minute = now_wib.minute
                    if current_hour in [8, 20] and current_hour != self.last_briefing_hour and current_minute <= 5:
                        label = "Pagi (08:00 WIB)" if current_hour == 8 else "Malam (20:00 WIB)"
                        digest = decision_engine.generate_executive_digest(label)
                        voice_file = await synthesize_voice_async(digest[:500])
                        await self.send_voice(session, self.authorized_chat_id, voice_file, caption=digest[:1024])
                        self.last_briefing_hour = current_hour

                    # 5. Periodic voice cache cleanup
                    if cycle_count % 30 == 0:
                        cleanup_temp_voice()

                    # 6. Email Cowork Triage (Every 180s)
                    if cycle_count % 3 == 0 and email_watchdog.is_configured():
                        triaged = email_watchdog.fetch_and_triage_unread()
                        for item in triaged:
                            await email_watchdog.send_email_alert(session, self.authorized_chat_id, item)

                    # 7. Production Systems Takeover & Auto-Replenish (Every 180s)
                    if cycle_count % 3 == 0:
                        kibot_controller.get_kibot_metrics()
                        threads_actions = threads_governor.evaluate_and_govern()
                        if threads_actions:
                            logger.info(f"🧵 Threads Governor Actions: {threads_actions}")

                    # 8. Full Autonomous Evolution & Production Governance (Every 600s / 10 mins)
                    if cycle_count % 10 == 0:
                        evolution_engine.audit_and_govern_production()

                except Exception as e:
                    logger.error(f"ANS loop exception: {e}")

                await asyncio.sleep(60)

    async def run(self):
        """Starts all concurrent background tasks."""
        logger.info("============================================================")
        logger.info("⚡ ZURA AUTONOMOUS PERSONAL AI ENGINE ONLINE ⚡")
        logger.info(f"Target Master: Kiki (Chat ID: {self.authorized_chat_id})")
        logger.info("============================================================")

        await asyncio.gather(
            self.telegram_polling_loop(),
            self.autonomic_ans_loop()
        )


if __name__ == "__main__":
    orchestrator = ZuraOrchestrator()
    try:
        asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        logger.info("Zura Orchestrator safely stopped by Master.")
