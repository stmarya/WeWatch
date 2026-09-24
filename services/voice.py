import threading
import logging
import os
import time
import asyncio
import edge_tts
import tempfile
from threading import Lock

is_speaking = False
_speech_lock = Lock()
# Suara Microsoft Edge Neural (Sangat Natural)
VOICE = "id-ID-ArdiNeural"

async def _generate_audio(text, filename):
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(filename)

def speak(text):
    global is_speaking
    if not text or not _speech_lock.acquire(blocking=False):
        return

    def run_speech():
        global is_speaking
        is_speaking = True
        filename = None
        try:
            from playsound import playsound

            with tempfile.NamedTemporaryFile(prefix="wewatch_voice_", suffix=".mp3", delete=False) as tmp:
                filename = tmp.name
            asyncio.run(_generate_audio(text, filename))
            playsound(filename)
        except Exception as e:
            logging.warning(f"edge-tts failed (maybe no internet): {e}. Falling back to pyttsx3.")
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.say(text)
                engine.runAndWait()
            except Exception as ex:
                logging.error(f"Fallback Voice TTS Error: {ex}")
        finally:
            is_speaking = False
            _speech_lock.release()
            if filename and os.path.exists(filename):
                try:
                    os.remove(filename)
                except OSError:
                    pass

    threading.Thread(target=run_speech, daemon=True).start()
