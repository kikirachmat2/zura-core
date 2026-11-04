"""
voice/tts.py - Edge-TTS Speech Synthesis for Zura
Generates natural young female voice (id-ID-GadisNeural / en-US-JennyNeural) 100% free.
"""

import os
import time
import asyncio
import edge_tts
from pathlib import Path
from core.config import VOICE_NAME_ID, VOICE_NAME_EN, TEMP_VOICE_DIR

TEMP_VOICE_DIR.mkdir(parents=True, exist_ok=True)


async def synthesize_voice_async(text: str, is_english: bool = False) -> str:
    """
    Synthesizes text into high-quality neural voice.
    Returns the path to the generated audio file.
    """
    voice = VOICE_NAME_EN if is_english else VOICE_NAME_ID
    filename = f"zura_voice_{int(time.time() * 1000)}.mp3"
    filepath = TEMP_VOICE_DIR / filename

    # Clean text to prevent SSML parsing issues
    clean_text = text.replace("*", "").replace("#", "").replace("`", "").strip()

    communicate = edge_tts.Communicate(clean_text, voice)
    await communicate.save(str(filepath))
    return str(filepath)


def synthesize_voice(text: str, is_english: bool = False) -> str:
    """Synchronous wrapper for synthesize_voice_async."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        # Running inside existing event loop
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, synthesize_voice_async(text, is_english))
            return future.result()
    else:
        return loop.run_until_complete(synthesize_voice_async(text, is_english))


def cleanup_temp_voice(max_age_seconds: int = 3600):
    """Purges audio files older than 1 hour to prevent disk bloat."""
    now = time.time()
    for f in TEMP_VOICE_DIR.glob("zura_voice_*.mp3"):
        try:
            if now - f.stat().st_mtime > max_age_seconds:
                f.unlink(missing_ok=True)
        except Exception:
            pass

