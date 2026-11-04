"""
voice/zura_siri.py - Hands-Free Siri-Style Voice Assistant for macOS
Enables Kiki to talk to Zura directly on MacBook Pro like Siri:
1. Plays activation chime (Glass.aiff)
2. Displays macOS Banner Notification
3. Records audio from MacBook Pro Microphone via ffmpeg
4. Transcribes via Groq Whisper-large-v3
5. Thinks via Gemini 3.5 Flash-lite (Zura Persona)
6. Synthesizes voice via Edge-TTS (id-ID-GadisNeural)
7. Speaks response aloud through Mac speakers (afplay)
"""

import os
import sys
import time
import argparse
import asyncio
import subprocess
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.brain import brain
from voice.stt import stt
from voice.tts import synthesize_voice_async
from core.config import TEMP_VOICE_DIR, TELEGRAM_CHAT_ID

CHIME_START = "/System/Library/Sounds/Glass.aiff"
CHIME_TICK = "/System/Library/Sounds/Tink.aiff"
CHIME_DONE = "/System/Library/Sounds/Pop.aiff"


def play_sound(sound_path: str):
    """Plays system sound asynchronously."""
    if os.path.exists(sound_path):
        subprocess.Popen(["afplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def show_mac_notification(title: str, message: str):
    """Displays a native macOS banner notification."""
    escaped_msg = message.replace('"', '\\"').replace("'", "")[:120]
    escaped_title = title.replace('"', '\\"')
    apple_script = f'display notification "{escaped_msg}" with title "{escaped_title}" sound name "Glass"'
    try:
        subprocess.run(["osascript", "-e", apple_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def record_microphone(output_path: str, duration: int = 4) -> bool:
    """Records audio from MacBook Pro Microphone using ffmpeg."""
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "avfoundation",
        "-i", ":0",
        "-t", str(duration),
        "-ar", "16000",
        "-ac", "1",
        output_path
    ]
    try:
        subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=duration + 3
        )
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
    except Exception as e:
        print(f"❌ Recording error: {e}")
        return False


async def talk_to_zura(duration: int = 4):
    """One complete conversational turn with Zura."""
    mic_audio = TEMP_VOICE_DIR / f"mic_{int(time.time()*1000)}.wav"
    TEMP_VOICE_DIR.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 55)
    print("🎙️ [ZURA] Mendengarkan Bos Kiki... (Silakan bicara)")
    print("=" * 55)
    
    # 1. Activation Chime & Notification
    play_sound(CHIME_START)
    show_mac_notification("ZURA Siri Voice", "Mendengarkan... Silakan bicara")

    # 2. Record
    success = record_microphone(str(mic_audio), duration=duration)
    if not success:
        print("❌ Gagal menangkap input audio dari mikrofon.")
        return

    # 3. Processing tick
    play_sound(CHIME_TICK)
    print("⚡ Mentranskripsi suara...")

    # 4. Speech to Text
    user_text = stt.transcribe(str(mic_audio))
    if not user_text or len(user_text.strip()) < 2:
        print("⚠️ Suara tidak terdeteksi atau terlalu sunyi.")
        play_sound(CHIME_DONE)
        return

    print(f"\n👤 Bos Kiki: \"{user_text}\"")

    # 5. Zura Brain Reasoning
    print("🧠 Zura sedang berpikir...")
    reply_text = brain.think(user_text, chat_id=TELEGRAM_CHAT_ID)
    print(f"🤖 Zura: \"{reply_text}\"\n")

    # 6. Show Mac Banner
    show_mac_notification("ZURA", reply_text[:100])

    # 7. Synthesize Edge-TTS & Speak
    print("🔊 Mengeluarkan suara Zura...")
    voice_path = await synthesize_voice_async(reply_text)
    if os.path.exists(voice_path):
        proc = subprocess.run(["afplay", voice_path])
    
    # Cleanup temp audio
    try:
        mic_audio.unlink(missing_ok=True)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Zura Siri-style voice assistant for macOS")
    parser.add_argument("--loop", action="store_true", help="Run in continuous walkie-talkie call loop")
    parser.add_argument("--duration", type=int, default=4, help="Recording duration in seconds (default: 4)")
    args = parser.parse_args()

    if args.loop:
        print("🚀 Zura Hands-Free Call Mode Aktif (Tekan Ctrl+C untuk berhenti)")
        try:
            while True:
                input("\n👉 Tekan [ENTER] untuk memanggil Zura...")
                asyncio.run(talk_to_zura(duration=args.duration))
        except KeyboardInterrupt:
            print("\n👋 Call selesai. Zura standby.")
    else:
        asyncio.run(talk_to_zura(duration=args.duration))


if __name__ == "__main__":
    main()

