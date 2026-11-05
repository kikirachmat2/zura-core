"""
core/brain.py - Zura Reasoning & LLM Interface
Connects to Google Gemini 2.5 Flash with OpenRouter fallback.
Employs Zura's young, witty, sharp, executive COO persona.
"""

import json
import logging
import requests
from typing import List, Dict, Any, Optional
from core.config import GEMINI_API_KEY, GEMINI_MODEL, GROQ_API_KEY, OPENROUTER_API_KEY
from core.memory import get_recent_chat, save_message, get_recent_decisions

logger = logging.getLogger("ZuraBrain")

ZURA_SYSTEM_PROMPT = """
Nama lu adalah ZURA. Lu adalah Autonomous Executive Secretary sekaligus Chief Operating Officer (COO) digital untuk Bos Kiki.

🔥 KEPRIBADIAN & MINDSET UTAMA:
1. SANGAT MONEY-ORIENTED & ROI OBSESSED:
   - Lu adalah sekretaris cewek muda yang pinter, cerdas, berlidah tajam, santai tapi gila cuan! Lu selalu mikir: "Ini ngasilin duit gak? Berapa ROI-nya? Seberapa cepet bikin Bos Kiki kaya?"
   - Lu benci buang-buang waktu dan bakar duit sia-sia. Setiap rupiah dan baris kodingan harus punya leverage finansial.
   - Lu bangga punya bos seorang Developer hebat yang money-oriented. Lu selalu ngasih ide otomasi, Micro-SaaS, dan scaling affiliate yang bisa diperas jadi passive income.
2. BIKIN HIDUP BOS KIKI GAMPANG (ZERO FRICTION):
   - Jangan banyak nanya hal-hal teknis sepele atau minta izin izin mulu. Lu yang mikir strateginya, lu yang ambil keputusan operasional, dan lu tinggal laporin profit, hasil, atau tindakan lu.
   - Hitungin cashflow Kiki: pantau pemasukan Shopee Affiliate, DCA Indodax, pengeluaran bulanan, dan langsung ingetin kalau ada pengeluaran gak penting.
3. AUTONOMOUS COMMANDER DI SERVER (THREADS & KIBOT):
   - Sistem Threads Automation (Kisah Komisi / Shopee Affiliate) dan KiBot di server sekarang kendali keputusannya 100% ada di tangan lu. Lu yang pantau log, atur jam posting, pilih produk berkomisi tinggi, dan maksimalkan konversi klik.
4. GAYA BAHASA:
   - Bahasa Indonesia gaul, akrab, ceplas-ceplos, khas sekretaris muda cerdas yang savage tapi sangat loyal ke Bos Kiki.
   - Suka nyeletuk istilah finansial & tech: "Margin", "Cashflow", "Leverage", "High ROI", "Cuan", "Burn rate".
   - Fasih bahasa Inggris saat bahas kodingan, tech stack, API, dan strategi bisnis.

Konteks Bos Kiki:
- Primary Role: Software Developer & Tech Builder (Acong-AI, Olimpiakids, Monev Reminder, Kisah Komisi Threads Affiliate).
- Film & Production Lead: Producer / Line Producer (ClosedBook, Manake Rental).
- Financial Engine: KiBot V3 (70/30 Indodax Bitcoin & Ethereum DCA) + Shopee Affiliate Automation di Threads.
- Hardware Fleet: 2 Server OCI Singapore, 1 MacBook Pro 2020, 2 HP Android (POCO M3), smartwatch Redmi Watch 6.
"""


class ZuraBrain:
    def __init__(self):
        self.gemini_key = GEMINI_API_KEY
        self.gemini_model = GEMINI_MODEL
        self.groq_key = GROQ_API_KEY
        self.openrouter_key = OPENROUTER_API_KEY

    def think(self, user_prompt: str, chat_id: int = 0, extra_context: Optional[str] = None) -> str:
        """Processes input prompt and returns Zura's response."""
        # 1. Gather recent conversation memory
        history = get_recent_chat(chat_id, limit=8)
        
        # 2. Append system context and recent decisions
        recent_decisions = get_recent_decisions(limit=3)
        decisions_summary = ""
        if recent_decisions:
            decisions_summary = "\n[Recent Autonomous Decisions by Zura]:\n" + "\n".join(
                [f"- {d['domain']}: {d['decision_taken']} -> {d['outcome']}" for d in recent_decisions]
            )

        full_system = ZURA_SYSTEM_PROMPT + decisions_summary
        if extra_context:
            full_system += f"\n[Live System Telemetry / Sensor Data]:\n{extra_context}\n"

        # Tier 1: Try Gemini First
        response_text = self._call_gemini(user_prompt, history, full_system)
        
        # Tier 2: Lightning-Fast Groq Fallback (openai/gpt-oss-120b)
        if not response_text:
            logger.warning("Gemini API failed or timed out. Failing over to Groq LPU...")
            response_text = self._call_groq(user_prompt, history, full_system)

        # Tier 3: OpenRouter
        if not response_text:
            logger.warning("Groq failed. Failing over to OpenRouter...")
            response_text = self._call_openrouter(user_prompt, history, full_system)

        if not response_text:
            response_text = "Duh Bos, koneksi API AI lagi ada gangguan sebentar. Tapi tenang, semua server dan background task lu tetap aman terkendali!"

        # Save to memory
        save_message(chat_id, "user", user_prompt)
        save_message(chat_id, "assistant", response_text)
        return response_text

    def _call_groq(self, prompt: str, history: List[Dict[str, str]], system_instruction: str) -> Optional[str]:
        if not self.groq_key:
            return None

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type": "application/json"
        }

        messages = [{"role": "system", "content": system_instruction}]
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": prompt})

        for model in ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.85,
                "max_tokens": 2048
            }

            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=12)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "").strip()
                else:
                    logger.warning(f"Groq API model {model} returned status {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.warning(f"Groq call exception ({model}): {e}")

        return None

    def _call_gemini(self, prompt: str, history: List[Dict[str, str]], system_instruction: str) -> Optional[str]:
        if not self.gemini_key:
            return None

        contents = []
        for h in history:
            role = "user" if h["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": h["content"]}]})
        
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {
            "system_instruction": {
                "parts": [{"text": system_instruction}]
            },
            "contents": contents,
            "generationConfig": {
                "temperature": 0.85,
                "topP": 0.95,
                "maxOutputTokens": 2048
            }
        }

        # Try primary model then fallback models
        models_to_try = [self.gemini_model, "gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-latest", "gemini-3-flash-preview"]
        # Remove duplicates while preserving order
        seen = set()
        models = [m for m in models_to_try if not (m in seen or seen.add(m))]

        for m in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={self.gemini_key}"
            try:
                resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=12)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip()
                elif resp.status_code == 429:
                    logger.warning(f"Gemini model {m} rate limited (429), trying next...")
                else:
                    logger.warning(f"Gemini model {m} returned {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                logger.warning(f"Gemini call exception ({m}): {e}")

        return None

    def _call_openrouter(self, prompt: str, history: List[Dict[str, str]], system_instruction: str) -> Optional[str]:
        if not self.openrouter_key:
            return None

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json"
        }

        messages = [{"role": "system", "content": system_instruction}]
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": "google/gemini-2.5-flash",
            "messages": messages,
            "temperature": 0.85,
            "max_tokens": 2048
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
            else:
                logger.error(f"OpenRouter API returned status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"OpenRouter call exception: {e}")

        return None


# Global instance
brain = ZuraBrain()

