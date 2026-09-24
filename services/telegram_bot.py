import os
import cv2
import time
import requests
import threading
import logging
from pathlib import Path
import uuid
from utils.security import Cooldown

BASE_DIR = Path(__file__).resolve().parent.parent
GALLERY_FOLDER = str(BASE_DIR / 'static' / 'gallery')
_alert_cooldown = Cooldown(seconds=15)

def send_telegram_alert(frame, caption, save_as="alert"):
    # Cool down by alert type, so a drowsiness alert cannot suppress
    # an unrelated security alert (and vice versa).
    if not _alert_cooldown.ready(save_as):
        return

    os.makedirs(GALLERY_FOLDER, exist_ok=True)
    filename = os.path.join(GALLERY_FOLDER, f"{save_as}_{uuid.uuid4().hex}.jpg")
    if not cv2.imwrite(filename, frame):
        logging.error("Failed to save Telegram alert frame: %s", filename)
        return
    
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        logging.warning("Telegram credentials not found in .env")
        return

    def send():
        try:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with open(filename, "rb") as f:
                response = requests.post(
                    url,
                    data={"chat_id": chat_id, "caption": caption},
                    files={"photo": f},
                    timeout=15,
                )
                if response.status_code != 200:
                    logging.error(f"Failed to send Telegram message: {response.text}")
                else:
                    logging.info(f"Telegram alert sent: {caption}")
        except Exception as e:
            logging.error(f"Telegram API Exception: {e}")
            
    threading.Thread(target=send, daemon=True).start()
