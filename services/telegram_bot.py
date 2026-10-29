import os
import cv2
import time
import requests
import threading
import logging
from pathlib import Path
import uuid
import io
from utils.security import Cooldown
from utils.deployment_security import parse_bool

BASE_DIR = Path(__file__).resolve().parent.parent
GALLERY_FOLDER = str(BASE_DIR / 'static' / 'gallery')
_alert_cooldown = Cooldown(seconds=15)

def send_telegram_alert(frame, caption, save_as="alert"):
    # Cool down by alert type, so a drowsiness alert cannot suppress
    # an unrelated security alert (and vice versa).
    if not _alert_cooldown.ready(save_as):
        return

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        logging.warning("Telegram credentials not found in .env")
        return

    encoded, buffer = cv2.imencode('.jpg', frame)
    if not encoded:
        logging.error("Failed to encode Telegram alert frame")
        return
    image_bytes = buffer.tobytes()
    save_copy = parse_bool(os.getenv('WEBWATCH_SAVE_ALERT_IMAGES'))
    filename = None
    if save_copy:
        os.makedirs(GALLERY_FOLDER, exist_ok=True)
        filename = os.path.join(GALLERY_FOLDER, f"{save_as}_{uuid.uuid4().hex}.jpg")
        if not cv2.imwrite(filename, frame):
            logging.error("Failed to save Telegram alert frame: %s", filename)
            return

    def send():
        try:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            if filename:
                with open(filename, "rb") as photo:
                    response = requests.post(
                        url,
                        data={"chat_id": chat_id, "caption": caption},
                        files={"photo": photo},
                        timeout=15,
                    )
            else:
                response = requests.post(
                    url,
                    data={"chat_id": chat_id, "caption": caption},
                    files={"photo": ("alert.jpg", io.BytesIO(image_bytes), "image/jpeg")},
                    timeout=15,
                )
            if response.status_code != 200:
                logging.error("Failed to send Telegram message: HTTP %s", response.status_code)
            else:
                logging.info("Telegram alert sent")
        except Exception as e:
            logging.error("Telegram API request failed (%s)", type(e).__name__)
            
    threading.Thread(target=send, daemon=True).start()
