import os
import cv2
import time
import requests
import threading
import logging

last_telegram_time = 0
GALLERY_FOLDER = os.path.join('static', 'gallery')

def send_telegram_alert(frame, caption, save_as="alert"):
    global last_telegram_time
    # Cooldown 15 detik agar tidak spam API
    if time.time() - last_telegram_time < 15:
        return
    
    last_telegram_time = time.time()
    os.makedirs(GALLERY_FOLDER, exist_ok=True)
    filename = os.path.join(GALLERY_FOLDER, f"{save_as}_{int(time.time())}.jpg")
    cv2.imwrite(filename, frame)
    
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        logging.warning("Telegram credentials not found in .env")
        return

    def send():
        try:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with open(filename, "rb") as f:
                response = requests.post(url, data={"chat_id": chat_id, "caption": caption}, files={"photo": f})
                if response.status_code != 200:
                    logging.error(f"Failed to send Telegram message: {response.text}")
                else:
                    logging.info(f"Telegram alert sent: {caption}")
        except Exception as e:
            logging.error(f"Telegram API Exception: {e}")
            
    threading.Thread(target=send).start()
