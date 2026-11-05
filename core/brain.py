"""
core/brain.py - Zura Reasoning & LLM Interface
Connects to Google Gemini 2.5 Flash with OpenRouter fallback.
Employs Zura's young, witty, sharp, executive COO persona.
"""

import os
import json
import logging
import requests
import psutil
from typing import List, Dict, Any, Optional
from core.config import GEMINI_API_KEY, GEMINI_MODEL, GROQ_API_KEY, OPENROUTER_API_KEY
from core.memory import get_recent_chat, save_message, get_recent_decisions, get_all_user_preferences

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
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")

    def think(self, user_prompt: str, chat_id: int = 0, extra_context: Optional[str] = None) -> str:
        """Processes input prompt and returns Zura's response."""
        # 1. Gather recent conversation memory & long-term episodic preferences
        history = get_recent_chat(chat_id, limit=8)
        user_prefs = get_all_user_preferences()
        prefs_summary = ""
        if user_prefs:
            prefs_summary = "\n[Permanent Memory - Bos Kiki Profile & Preferences]:\n" + "\n".join(
                [f"- {k}: {v}" for k, v in user_prefs.items()]
            )

        # 2. Situational EQ & Mood Detection (Adaptive Persona Switcher)
        prompt_lower = user_prompt.lower()
        fatigue_keywords = [
            "capek", "lelah", "pusing", "mumet", "drop", "sakit", "stress",
            "berat", "istirahat", "tidur", "burnout", "penat", "pegel",
            "shooting", "syuting", "manake"
        ]
        is_user_fatigued = any(k in prompt_lower for k in fatigue_keywords)
        eq_inject = ""
        if is_user_fatigued:
            eq_inject = (
                "\n[SITUATIONAL EQ PROTOCOL - EMPATHETIC CALM MODE ACTIVE]:\n"
                "- Bos Kiki terdeteksi sedang lelah fisik/mental atau baru selesai produksi lapangan.\n"
                "- TURUNKAN sarkasme dan nada tajam. DILARANG menagih ROI, cuan, atau membicarakan beban kerja baru.\n"
                "- Berikan jawaban yang menenangkan, suportif, santun, dan ringkas.\n"
                "- REASSURANCE: Tegaskan bahwa seluruh armada (server SG1/SG2, KiBot, dan Threads) berjalan 100% aman dan terkendali, sehingga Bos Kiki bisa beristirahat dengan tenang tanpa khawatir.\n"
            )

        # 3. Append system context and recent decisions
        recent_decisions = get_recent_decisions(limit=3)
        decisions_summary = ""
        if recent_decisions:
            decisions_summary = "\n[Recent Autonomous Decisions by Zura]:\n" + "\n".join(
                [f"- {d['domain']}: {d['decision_taken']} -> {d['outcome']}" for d in recent_decisions]
            )

        full_system = ZURA_SYSTEM_PROMPT + prefs_summary + eq_inject + decisions_summary
        if extra_context:
            full_system += f"\n[Live System Telemetry / Sensor Data]:\n{extra_context}\n"

        # Tier 1: Try Gemini First
        response_text = self._call_gemini(user_prompt, history, full_system)
        
        # Tier 2: Lightning-Fast Groq Fallback (openai/gpt-oss-120b)
        if not response_text:
            logger.warning("Gemini API failed or timed out. Failing over to Groq LPU...")
            response_text = self._call_groq(user_prompt, history, full_system)

        # Tier 3: Adaptive Local Ollama (Only if system RAM capacity allows >= 1.5GB)
        if not response_text:
            response_text = self._call_ollama(user_prompt, history, full_system)

        # Tier 4: OpenRouter
        if not response_text:
            logger.warning("Groq/Ollama failed. Failing over to OpenRouter...")
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

        for model in ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]:
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
        models_to_try = [self.gemini_model, "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.1-flash-lite"]
        # Remove duplicates while preserving order
        seen = set()
        models = [m for m in models_to_try if not (m in seen or seen.add(m))]

        for m in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={self.gemini_key}"
            try:
                resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=5.0)
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

    def _call_ollama(self, prompt: str, history: List[Dict[str, str]], system_instruction: str) -> Optional[str]:
        """
        Adaptive local Ollama client:
        - Evaluates system RAM before dispatching.
        - Skips execution if available RAM < 1.5GB to avoid OOM-killing critical services on low-memory servers (e.g. Server 1 952MB RAM).
        - Executes locally on capable machines (e.g. Mac 16GB RAM) via lightweight local models.
        """
        try:
            mem = psutil.virtual_memory()
            avail_mb = mem.available / (1024 * 1024)
            if avail_mb < 1500.0:
                logger.info(
                    "Ollama local inference bypassed: available RAM (%.1f MB) < 1500 MB (avoiding Linux OOM crash).",
                    avail_mb
                )
                return None

            url = f"{self.ollama_host.rstrip('/')}/api/generate"
            formatted_prompt = f"System: {system_instruction}\n\n"
            for h in history:
                formatted_prompt += f"{h['role'].capitalize()}: {h['content']}\n"
            formatted_prompt += f"User: {prompt}\nAssistant:"

            payload = {
                "model": self.ollama_model,
                "prompt": formatted_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.8,
                    "num_predict": 1024
                }
            }

            resp = requests.post(url, json=payload, timeout=8.0)
            if resp.status_code == 200:
                data = resp.json()
                res_text = data.get("response", "").strip()
                if res_text:
                    logger.info("Ollama local inference succeeded using model '%s'", self.ollama_model)
                    return res_text
        except Exception as e:
            logger.debug("Ollama local connection skipped or unreachable: %s", e)

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

