"""
core/email_watchdog.py - Zura Autonomous Email, Cowork & Financial Watchdog
Runs on Server 1 (24/7) and Mac:
1. Monitors unread emails via IMAP (Gmail / Workspace) using intelligent time-window filters
2. Autonomously parses Bank & E-Wallet Transaction alerts (myBCA, Mandiri, Jago, GoPay, etc.)
   - Extracts nominal amount, merchant/beneficiary, category (Transport, Food, Shopping, Transfer)
   - Automatically records transaction into Zura's Financial Ledger
   - Dispatches instant formatted financial transaction alerts to Kiki on Telegram
3. Cowork & Client Triage: Summarizes emails, detects meeting links (Google Meet/Zoom), drafts replies
4. SMTP 1-Click Dispatch: Sends replies directly from configured user email
5. Subscription Vampire Hunter: Scans for recurring SaaS/service subscriptions (Cursor, Google One, Apple, etc.)
6. Security Early-Warning Sentinel: Intercepts Google, GitHub, OCI security warnings
"""

import os
import sys
import time
import re
import imaplib
import smtplib
import email
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from html import unescape
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.config import (
    EMAIL_IMAP_SERVER, EMAIL_USER, EMAIL_PASSWORD, EMAIL_PORT,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
)
from core.brain import brain
from core.memory import log_decision, get_state, set_state, record_transaction, get_monthly_finance_summary

logger = logging.getLogger("EmailWatchdog")


def clean_header(header_str: str) -> str:
    """Decodes MIME encoded email headers."""
    if not header_str:
        return ""
    decoded_parts = decode_header(header_str)
    res = []
    for text, enc in decoded_parts:
        if isinstance(text, bytes):
            try:
                res.append(text.decode(enc or "utf-8", errors="ignore"))
            except Exception:
                res.append(text.decode("latin1", errors="ignore"))
        else:
            res.append(str(text))
    return " ".join(res).strip()


def extract_body(msg) -> str:
    """Extracts plain text content from email message, falling back to cleaned HTML."""
    body = ""
    html_fallback = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                continue

            if content_type == "text/plain" and not body:
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="ignore")
            elif content_type == "text/html" and not html_fallback:
                payload = part.get_payload(decode=True)
                if payload:
                    html_fallback = payload.decode("utf-8", errors="ignore")
    else:
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            if content_type == "text/plain":
                body = payload.decode("utf-8", errors="ignore")
            elif content_type == "text/html":
                html_fallback = payload.decode("utf-8", errors="ignore")

    # If no plain text, sanitize HTML
    if not body and html_fallback:
        clean = re.sub(r"<style.*?</style>", "", html_fallback, flags=re.DOTALL)
        clean = re.sub(r"<script.*?</script>", "", clean, flags=re.DOTALL)
        clean = re.sub(r"<[^>]+>", " ", clean)
        clean = unescape(clean)
        body = re.sub(r"\s+", " ", clean).strip()

    return body.strip()[:3500]


class EmailWatchdog:
    URGENT_KEYWORDS = [
        "urgent", "asap", "penting", "revisi", "deadline", "call sheet",
        "shooting", "syuting", "rental", "kamera", "invoice", "dp", "pelunasan",
        "brief", "naskah", "jadwal", "casting", "crew", "kibot", "server", "kontrak"
    ]

    BANK_SENDERS = [
        "bca.co.id", "bankmandiri.co.id", "jago.com", "bni.co.id", "bri.co.id",
        "gopay.co.id", "ovo.id", "dana.id", "shopeepay", "cimbniaga.co.id"
    ]

    SECURITY_KEYWORDS = [
        "security alert", "unrecognized device", "suspicious activity",
        "peringatan keamanan", "login dari perangkat baru", "password reset", "2-step verification"
    ]

    def __init__(self):
        self.server = EMAIL_IMAP_SERVER
        self.user = EMAIL_USER
        self.password = EMAIL_PASSWORD
        self.port = EMAIL_PORT
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 465
        
        # Load persisted processed IDs to avoid repeat alerts across restarts
        saved = get_state("processed_email_ids", [])
        self.processed_ids = set(saved) if isinstance(saved, list) else set()

    def is_configured(self) -> bool:
        """Checks if valid email credentials exist in environment."""
        return bool(self.user and self.password and "@" in self.user)

    def _categorize_expense(self, merchant: str, tx_type: str) -> str:
        """Categorizes transaction based on merchant and transaction type."""
        m_lower = (merchant + " " + tx_type).lower()
        if any(k in m_lower for k in ["grab", "gojek", "goride", "gocar", "bluebird", "kai", "mrt", "krl", "toll", "bensin", "pertamina"]):
            return "Transport"
        if any(k in m_lower for k in ["kopi", "coffee", "fore", "starbucks", "kenangan", "cafe", "resto", "mcd", "kfc", "hokben", "bakso", "nasi", "mie"]):
            return "Food & Beverage"
        if any(k in m_lower for k in ["shopee", "tokopedia", "lazada", "blibli", "indomaret", "alfamart", "supermarket"]):
            return "Shopping / Retail"
        if any(k in m_lower for k in ["pln", "telkom", "indihome", "biznet", "pulsa", "kuota", "pdam"]):
            return "Utilities & Bills"
        if any(k in m_lower for k in ["transfer", "antar bank", "rekening"]):
            return "Transfer"
        return "Operational / Expense"

    def _parse_financial_transaction(self, sender: str, subject: str, body: str, date_str: str) -> Optional[Dict[str, Any]]:
        """Parses bank receipts (myBCA, Mandiri, etc.) into structured records."""
        sender_lower = sender.lower()
        subject_lower = subject.lower()

        is_bank = any(b in sender_lower for b in self.BANK_SENDERS) or any(
            kw in subject_lower for kw in ["transaction journal", "qris payment", "notifikasi transaksi", "transfer berhasil"]
        )
        if not is_bank:
            return None

        # 1. Extract Amount
        amt_m = re.search(r"(?:Total Payment|Transfer Amount|Amount|Jumlah|Nominal|Total Transaksi)\s*:\s*(?:IDR|Rp)?\s*([0-9,.]+)", body, re.IGNORECASE)
        if not amt_m:
            return None

        amt_raw = amt_m.group(1).replace(",", "")
        try:
            amount = float(amt_raw)
        except ValueError:
            return None

        # 2. Extract Transaction Type
        type_m = re.search(r"(?:Transaction Type|Transfer Type|Jenis Transaksi)\s*:\s*([^:\n\r]+?)(?:Payment to|Beneficiary|Source|Status|$)", body, re.IGNORECASE)
        tx_type = type_m.group(1).strip() if type_m else "Payment / Transfer"

        # 3. Extract Target / Merchant
        target_m = re.search(r"(?:Payment to|Beneficiary Name|Penerima|Tujuan|Merchant)\s*:\s*([^:\n\r]+?)(?:Merchant Location|Save to|Transfer Amount|Remarks|Reference|Customer PAN|RRN|Terminal|Source|$)", body, re.IGNORECASE)
        target = target_m.group(1).strip() if target_m else "Merchant / Penerima"

        # 4. Extract Source
        src_m = re.search(r"(?:Source of Fund|Dari Rekening)\s*:\s*([^:\n\r]+?)(?:Customer PAN|Source Currency|Transfer Currency|$)", body, re.IGNORECASE)
        source_fund = src_m.group(1).strip() if src_m else "Rekening BCA"

        # 5. Determine Flow Type (Income vs Expense)
        flow_type = "expense"
        if any(kw in body.lower() or kw in subject_lower for kw in ["transfer masuk", "dana masuk", "top up masuk", "refund", "credit"]):
            flow_type = "income"

        # 6. Categorize
        category = self._categorize_expense(target, tx_type)

        # 7. Format Date (YYYY-MM-DD)
        tx_date = datetime.now().strftime("%Y-%m-%d")
        date_clean = date_str[:25]

        # Record to Zura Financial Database
        record_transaction(
            amount=amount,
            flow_type=flow_type,
            category=category,
            description=f"{tx_type}: {target}",
            source=source_fund,
            tx_date=tx_date
        )

        return {
            "type": "financial",
            "flow_type": flow_type,
            "amount": amount,
            "tx_type": tx_type,
            "target": target,
            "source_fund": source_fund,
            "category": category,
            "date_display": date_clean
        }

    def fetch_and_triage_unread(self) -> List[Dict[str, Any]]:
        """Connects to IMAP, retrieves recent unseen emails, and triages them."""
        if not self.is_configured():
            logger.debug("Email credentials not configured in .env. Skipping check.")
            return []

        triaged_items = []
        mail = None

        try:
            mail = imaplib.IMAP4_SSL(self.server, self.port)
            mail.login(self.user, self.password)
            mail.select("INBOX")

            # Efficient search: look for unread emails within the last 2 days
            since_date = (datetime.now() - timedelta(days=2)).strftime("%d-%b-%Y")
            status, messages = mail.search(None, f'(UNSEEN SINCE "{since_date}")')
            
            # Fallback to general UNSEEN if since_date returns empty
            if status != "OK" or not messages[0]:
                status, messages = mail.search(None, "UNSEEN")

            if status != "OK" or not messages[0]:
                return []

            msg_ids = messages[0].split()
            # Process up to 5 latest unread emails in this cycle
            for mid in msg_ids[-5:]:
                mid_str = mid.decode()
                if mid_str in self.processed_ids:
                    continue

                res, data = mail.fetch(mid, "(RFC822)")
                if res != "OK":
                    continue

                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                sender = clean_header(msg.get("From", "Unknown"))
                subject = clean_header(msg.get("Subject", "(No Subject)"))
                date_str = clean_header(msg.get("Date", ""))
                body = extract_body(msg)
                sender_lower = sender.lower()
                subject_lower = subject.lower()

                # 1. Security Alert Interceptor
                is_security = any(kw in subject_lower for kw in self.SECURITY_KEYWORDS)
                if is_security:
                    self.processed_ids.add(mid_str)
                    triaged_items.append({
                        "type": "security",
                        "id": mid_str,
                        "sender": sender,
                        "subject": subject,
                        "body_excerpt": body[:500],
                        "date_display": date_str[:25]
                    })
                    continue

                # 2. Check if this is a Financial Transaction Alert
                fin_record = self._parse_financial_transaction(sender, subject, body, date_str)
                if fin_record:
                    fin_record["id"] = mid_str
                    fin_record["sender"] = sender
                    fin_record["subject"] = subject
                    triaged_items.append(fin_record)
                    self.processed_ids.add(mid_str)

                    log_decision(
                        domain="Finance Tracker",
                        trigger_event=f"Bank alert parsed: {fin_record['tx_type']} Rp {fin_record['amount']:,.0f}",
                        decision_taken="Recorded transaction into financial_ledger",
                        outcome=f"Category: {fin_record['category']} | Target: {fin_record['target']}"
                    )
                    continue

                # 3. Filter newsletters / spam
                is_spam = any(spam_term in sender_lower or spam_term in subject_lower for spam_term in [
                    "noreply", "no-reply", "newsletter", "marketing", "promo", "promo@", "linkedin",
                    "facebook", "instagram", "tiktok", "update@", "mailer"
                ])

                if is_spam:
                    self.processed_ids.add(mid_str)
                    continue

                # 4. Meeting Link Extractor (Google Meet / Zoom / Microsoft Teams)
                meet_links = re.findall(r"(https?://(?:meet\.google\.com/[a-z0-9-]+|[a-z0-9.]*zoom\.us/j/[0-9]+|teams\.microsoft\.com/l/meetup-join/[^\s\>\"]+))", body)
                meeting_url = meet_links[0] if meet_links else None

                # 5. Cowork / Client Priority Email Triage
                is_urgent = any(kw in subject_lower or kw in body.lower() for kw in self.URGENT_KEYWORDS)

                prompt = (
                    f"Ini email yang masuk untuk Bos Kiki.\n"
                    f"Dari: {sender}\n"
                    f"Subjek: {subject}\n"
                    f"Isi: {body[:1500]}\n\n"
                    f"Tugas lu sebagai Zura (Sekretaris Eksekutif & Asisten Pribadi Bos Kiki):\n"
                    f"1. Buat ringkasan 2 kalimat tentang maksud utama email ini dan action item yang harus dikerjakan.\n"
                    f"2. Buatkan 1 draf balasan singkat, profesional dan lugas khas anak muda tech yang siap dikirim Kiki.\n"
                    f"Format output:\n"
                    f"RINGKASAN: [ringkasan]\n"
                    f"DRAF BALASAN: [isi balasan]"
                )

                analysis = brain.think(prompt, chat_id=TELEGRAM_CHAT_ID)
                self.processed_ids.add(mid_str)

                # Extract drafted reply text
                draf_reply = ""
                if "DRAF BALASAN:" in analysis:
                    draf_reply = analysis.split("DRAF BALASAN:")[1].strip()

                parsed_data = {
                    "type": "cowork",
                    "id": mid_str,
                    "sender": sender,
                    "subject": subject,
                    "is_urgent": is_urgent,
                    "meeting_url": meeting_url,
                    "analysis": analysis,
                    "draf_reply": draf_reply,
                    "timestamp": time.time()
                }
                triaged_items.append(parsed_data)

                # Save pending draft so Kiki can trigger 1-click send via Telegram
                pending_drafts = get_state("pending_email_drafts", {})
                pending_drafts[mid_str] = {
                    "to": sender,
                    "subject": f"Re: {subject}",
                    "draft": draf_reply,
                    "created_at": time.time()
                }
                set_state("pending_email_drafts", pending_drafts)

                log_decision(
                    domain="Email Cowork Assistant",
                    trigger_event=f"Email received from {sender}: '{subject[:40]}...'",
                    decision_taken="Triaged and generated AI draft response",
                    outcome=f"Queued draft ID {mid_str} for Kiki's 1-click dispatch"
                )

            # Persist state
            set_state("processed_email_ids", list(self.processed_ids)[-200:])

        except Exception as e:
            logger.error(f"IMAP Fetch exception: {e}")
        finally:
            if mail:
                try:
                    mail.close()
                    mail.logout()
                except Exception:
                    pass

        return triaged_items

    def send_reply(self, to_email: str, subject: str, body_text: str) -> Dict[str, Any]:
        """Dispatches email reply via Google SMTP SSL on behalf of Kiki."""
        if not self.is_configured():
            return {"success": False, "error": "Email not configured"}

        # Extract pure email from "Name <email@domain.com>"
        match = re.search(r"<([^>]+)>", to_email)
        recipient = match.group(1) if match else to_email.strip()

        msg = MIMEMultipart()
        sender_name = os.getenv("EMAIL_SENDER_NAME", "Executive Secretary")
        msg["From"] = f"{sender_name} <{self.user}>"
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

        try:
            with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=15) as server:
                server.login(self.user, self.password)
                server.send_message(msg)
            
            log_decision(
                domain="Email SMTP Dispatcher",
                trigger_event=f"Authorized 1-click send to {recipient}",
                decision_taken=f"Sent email with subject: {subject}",
                outcome="Delivered via Google SMTP"
            )
            return {"success": True, "recipient": recipient}
        except Exception as e:
            logger.error(f"SMTP send failed: {e}")
            return {"success": False, "error": str(e)}

    def audit_subscriptions(self, days: int = 60) -> List[Dict[str, Any]]:
        """Scans mailbox for recurring SaaS & service subscriptions (Cursor, Google, Apple, etc.)."""
        if not self.is_configured():
            return []

        mail = None
        subscriptions = []
        try:
            mail = imaplib.IMAP4_SSL(self.server, self.port)
            mail.login(self.user, self.password)
            mail.select("INBOX")

            since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
            
            # Search candidate subjects
            found_ids = set()
            for kw in ["subscription", "invoice", "receipt", "billing", "tagihan", "google one", "apple.com"]:
                typ, msgs = mail.search(None, f'(SUBJECT "{kw}" SINCE "{since_date}")')
                if typ == "OK" and msgs[0]:
                    for mid in msgs[0].split():
                        found_ids.add(mid)

            for mid in list(found_ids)[-25:]:
                res, data = mail.fetch(mid, "(RFC822)")
                if res != "OK":
                    continue
                msg = email.message_from_bytes(data[0][1])
                sender = clean_header(msg.get("From", ""))
                subject = clean_header(msg.get("Subject", ""))
                body = extract_body(msg)

                # Match nominal cost
                amt_m = re.search(r"(?:Total|Price|Tarif|Nominal|Jumlah|Tagihan)?\s*[:\s]?(?:IDR|Rp|\$)\s*([0-9,.]+)", body)
                amt_str = amt_m.group(1) if amt_m else "N/A"

                subscriptions.append({
                    "service": sender[:40],
                    "subject": subject[:50],
                    "cost_estimate": amt_str,
                    "date": clean_header(msg.get("Date", ""))[:20]
                })

        except Exception as e:
            logger.error(f"Subscription audit exception: {e}")
        finally:
            if mail:
                try:
                    mail.close()
                    mail.logout()
                except Exception:
                    pass

        return subscriptions

    async def send_email_alert(self, session, chat_id: int, item: dict):
        """Sends formatted Telegram alert for financial, security, or cowork emails."""
        item_type = item.get("type", "cowork")

        if item_type == "financial":
            flow_icon = "💸 <b>PENGELUARAN TERCATAT (myBCA)</b>" if item["flow_type"] == "expense" else "💰 <b>PEMASUKAN TERCATAT!</b>"
            monthly = get_monthly_finance_summary()
            
            msg = (
                f"{flow_icon}\n\n"
                f"💵 <b>Nominal:</b> <code>Rp {item['amount']:,.0f}</code>\n"
                f"🏢 <b>Penerima / Merchant:</b> <b>{item['target']}</b>\n"
                f"🏷️ <b>Kategori:</b> {item['category']} ({item['tx_type']})\n"
                f"💳 <b>Sumber Dana:</b> <code>{item['source_fund']}</code>\n"
                f"📅 <b>Waktu:</b> {item.get('date_display', 'Hari ini')}\n\n"
                f"📊 <b>Total Burn Rate Bulan Ini:</b> Rp {monthly['expense_idr']:,.0f}\n"
                f"<i>Otomatis Zura catat ke ledger buku kas lu, Bos!</i>"
            )
        elif item_type == "security":
            msg = (
                f"🚨 <b>PERINGATAN KEAMANAN AKUN!</b>\n\n"
                f"👤 <b>Dari:</b> <code>{item['sender']}</code>\n"
                f"📌 <b>Subjek:</b> <b>{item['subject']}</b>\n"
                f"📅 <b>Waktu:</b> {item['date_display']}\n\n"
                f"📝 <b>Isi Peringatan:</b>\n<i>{item['body_excerpt']}</i>\n\n"
                f"⚠️ <i>Zura sarankan cek perangkat atau aktivitas login lu sekarang kalau bukan lu yang lakuin!</i>"
            )
        else:
            priority_tag = "🚨 <b>EMAIL URGENT COWORK!</b>" if item.get("is_urgent") else "📧 <b>EMAIL KERJAAN MASUK</b>"
            meet_badge = f"\n🔗 <b>Link Meeting Terdeteksi:</b> {item['meeting_url']}\n" if item.get("meeting_url") else ""
            msg = (
                f"{priority_tag}\n\n"
                f"👤 <b>Dari:</b> <code>{item['sender']}</code>\n"
                f"📌 <b>Subjek:</b> <b>{item['subject']}</b>\n"
                f"{meet_badge}\n"
                f"{item['analysis']}\n\n"
                f"🚀 <b>1-Click Reply:</b> Ketik <code>/reply {item['id']}</code> untuk langsung kirim draf balasan di atas ke pengirim!"
            )

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            async with session.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=10) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"Error sending email alert to Telegram: {e}")


# Global instance
email_watchdog = EmailWatchdog()
