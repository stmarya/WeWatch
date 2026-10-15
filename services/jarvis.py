import threading
import time
import logging
import os
from services.voice import speak

try:
    import speech_recognition as sr
    HAS_SR = True
except ImportError:
    HAS_SR = False

def jarvis_listener(camera):
    if os.getenv('VOICE_CLOUD_ENABLED', 'false').lower() != 'true':
        logging.info('Cloud speech recognition disabled by privacy policy')
        return
    if not HAS_SR:
        print("JARVIS ERROR: Modul speech_recognition tidak terinstal.")
        return
        
    recognizer = sr.Recognizer()
    try:
        mic = sr.Microphone()
    except Exception as e:
        print(f"JARVIS ERROR: Mikrofon tidak terdeteksi. {e}")
        return

    print("🎙️ Jarvis Listener Started...")
    
    with mic as source:
        recognizer.adjust_for_ambient_noise(source)

    while True:
        try:
            if not camera.features.get('voice_command', False):
                time.sleep(1)
                continue
                
            with mic as source:
                audio = recognizer.listen(source, timeout=2, phrase_time_limit=4)
            
            text = recognizer.recognize_google(audio, language="id-ID").lower()
            camera.status['last_command'] = text
            
            if "jarvis" in text:
                if "nyalakan" in text or "aktifkan" in text:
                    if "blur" in text:
                        camera.set_feature('blur', True)
                        speak("Sistem penyamaran diaktifkan.")
                    elif "kacamata" in text:
                        camera.set_feature('kacamata', True)
                        speak("Kacamata diaktifkan.")
                    elif "kantuk" in text:
                        camera.set_feature('kantuk', True)
                        speak("Pendeteksi kantuk siap.")
                    elif "keamanan" in text:
                        speak("Ubah pengaturan keamanan lewat dashboard admin.")
                        
                elif "matikan" in text or "nonaktifkan" in text:
                    if "blur" in text:
                        camera.set_feature('blur', False)
                        speak("Sistem penyamaran dinonaktifkan.")
                    elif "kacamata" in text:
                        camera.set_feature('kacamata', False)
                        speak("Kacamata dilepas.")
                    elif "kantuk" in text:
                        camera.set_feature('kantuk', False)
                        speak("Pendeteksi kantuk dihentikan.")
                    elif "keamanan" in text:
                        speak("Pengaturan keamanan tidak dapat diubah lewat suara.")
                        
        except sr.WaitTimeoutError:
            continue
        except sr.UnknownValueError:
            logging.debug("Jarvis could not understand the audio")
        except Exception as e:
            logging.exception("Jarvis listener error: %s", e)
            time.sleep(1)

def start_jarvis(camera):
    thread = threading.Thread(target=jarvis_listener, args=(camera,), daemon=True)
    thread.start()
