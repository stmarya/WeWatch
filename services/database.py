import sqlite3
import datetime
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def _connect(path):
    """Create a short-lived connection that behaves well with worker threads."""
    path = Path(path)
    if not path.is_absolute():
        path = BASE_DIR / path
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db():
    conn = _connect('mood.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS mood (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    waktu TEXT,
                    emosi TEXT)''')
    conn.commit()
    conn.close()

def init_attendance_db():
    conn = _connect('attendance.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    date TEXT,
                    clock_in TEXT,
                    total_seconds INTEGER)''')
    conn.commit()
    conn.close()

def insert_mood(emosi):
    try:
        conn = _connect('mood.db')
        c = conn.cursor()
        c.execute("INSERT INTO mood (waktu, emosi) VALUES (?, ?)", (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), emosi))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Failed to insert mood: {e}")

def log_clock_in(name):
    try:
        conn = _connect('attendance.db')
        c = conn.cursor()
        date_today = datetime.datetime.now().strftime("%Y-%m-%d")
        c.execute("SELECT * FROM attendance WHERE name=? AND date=?", (name, date_today))
        if not c.fetchone():
            c.execute("INSERT INTO attendance (name, date, clock_in, total_seconds) VALUES (?, ?, ?, 0)", 
                      (name, date_today, datetime.datetime.now().strftime("%H:%M:%S")))
            conn.commit()
            logging.info(f"Attendance: {name} CLOCKED IN at {datetime.datetime.now().strftime('%H:%M:%S')}")
        conn.close()
    except Exception as e:
        import logging
        logging.error(f"Failed to log clock in: {e}")

def update_work_time(name, add_seconds=1):
    try:
        conn = _connect('attendance.db')
        c = conn.cursor()
        date_today = datetime.datetime.now().strftime("%Y-%m-%d")
        c.execute("UPDATE attendance SET total_seconds = total_seconds + ? WHERE name=? AND date=?", (add_seconds, name, date_today))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Failed to update work time: {e}")
