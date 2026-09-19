import threading
import time
import logging

def start_services():
    # 1. Jalankan Web Server di background
    from app import run_web_server
    threading.Thread(target=run_web_server, daemon=True).start()
    logging.info("Web Server Thread Started.")
    
    # Beri jeda sedikit agar server web siap
    time.sleep(1)

    # 2. Jalankan Desktop GUI di Main Thread
    from desktop_app import DesktopApp
    logging.info("Memulai Desktop GUI...")
    app = DesktopApp()
    app.mainloop()

if __name__ == "__main__":
    start_services()
