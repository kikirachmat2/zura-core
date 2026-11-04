"""
voice/stt.py - Speech-to-Text via Groq Whisper Large V3
Transcribes voice notes and incoming audio with <300ms latency.
"""

import os
import logging
from groq import Groq
from core.config import GROQ_API_KEY, STT_MODEL

logger = logging.getLogger("ZuraSTT")


class ZuraSTT:
    def __init__(self):
        self.api_key = GROQ_API_KEY
        self.client = Groq(api_key=self.api_key) if self.api_key else None
        self.model = STT_MODEL

    def transcribe(self, audio_file_path: str, language: str = "id") -> str:
        """Transcribes audio file to text."""
        if not self.client:
            logger.error("Groq client not initialized. Missing GROQ_API_KEY.")
            return ""

        if not os.path.exists(audio_file_path):
            logger.error(f"Audio file not found: {audio_file_path}")
            return ""

        try:
            with open(audio_file_path, "rb") as file:
                transcription = self.client.audio.transcriptions.create(
                    file=(os.path.basename(audio_file_path), file.read()),
                    model=self.model,
                    language=language,
                    temperature=0.0
                )
                return transcription.text.strip()
        except Exception as e:
            logger.error(f"Groq transcription error: {e}")
            return ""


# Global STT instance
stt = ZuraSTT()

