"""Authenticated Windows desktop agent for WeWatch.

The agent accepts only structured, allowlisted commands from the signaling
server. It never executes arbitrary shell commands.

Required environment:
  WEBRTC_SERVER_URL=http://localhost:5001
  DESKTOP_AGENT_TOKEN=...
  DESKTOP_AGENT_IDENTITY=workstation-01
  DESKTOP_AGENT_TARGET_IDENTITY=<client identity from the browser join>
"""

from __future__ import annotations

import base64
import io
import logging
import os
import platform
import subprocess
import threading
import time
import uuid
import webbrowser
from collections import deque

try:
    import socketio
except ImportError as exc:
    raise SystemExit("Install dependencies first: pip install -r requirements.txt") from exc
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SERVER_URL = os.getenv("WEBRTC_SERVER_URL", "http://localhost:5001")
AGENT_TOKEN = os.getenv("DESKTOP_AGENT_TOKEN", "").strip()
AGENT_IDENTITY = os.getenv("DESKTOP_AGENT_IDENTITY", platform.node() or "desktop-agent")
TARGET_IDENTITY = os.getenv("DESKTOP_AGENT_TARGET_IDENTITY", "").strip()
ALLOW_DANGEROUS = os.getenv("DESKTOP_AGENT_ALLOW_DANGEROUS", "false").lower() == "true"
ALLOWED_PROCESSES = {
    item.strip().lower()
    for item in os.getenv("DESKTOP_AGENT_ALLOWED_PROCESSES", "").split(",")
    if item.strip()
}

try:
    import pyautogui
    pyautogui.FAILSAFE = True
except Exception:
    pyautogui = None


def _result(ok, message, screenshot_b64=None):
    result = {"ok": ok, "message": str(message)[:1000]}
    if screenshot_b64:
        result["screenshot_b64"] = screenshot_b64
    return result


def _require_desktop():
    if pyautogui is None:
        raise RuntimeError("pyautogui is not available on this workstation")


def _ratio(value):
    return max(0.0, min(1.0, float(value)))


def _safe_url(value):
    value = str(value or "").strip()
    if not value.startswith(("https://", "http://")):
        raise ValueError("Only http:// and https:// URLs are allowed")
    return value[:2048]


def execute_command(command, payload):
    """Execute one allowlisted command and return a serializable result."""
    payload = payload if isinstance(payload, dict) else {}

    if command == "mouse_move":
        _require_desktop()
        width, height = pyautogui.size()
        pyautogui.moveTo(int(_ratio(payload.get("xRatio", 0)) * width),
                         int(_ratio(payload.get("yRatio", 0)) * height))
        return _result(True, "Mouse moved")

    if command == "mouse_click":
        _require_desktop()
        width, height = pyautogui.size()
        button = payload.get("button", "left")
        if button not in {"left", "right", "double", "middle"}:
            raise ValueError("Unsupported mouse button")
        x = int(_ratio(payload.get("xRatio", 0)) * width)
        y = int(_ratio(payload.get("yRatio", 0)) * height)
        if button == "double":
            pyautogui.doubleClick(x, y)
        else:
            getattr(pyautogui, f"{button}Click")(x, y)
        return _result(True, "Mouse click completed")

    if command == "mouse_scroll":
        _require_desktop()
        delta = max(-1200, min(1200, int(payload.get("deltaY", 0))))
        pyautogui.scroll(delta)
        return _result(True, "Mouse scrolled")

    if command == "key_input":
        _require_desktop()
        input_type = payload.get("type")
        value = payload.get("value")
        if input_type == "text" and isinstance(value, str) and len(value) <= 2000:
            pyautogui.write(value, interval=0.005)
        elif input_type == "key" and isinstance(value, str) and len(value) <= 32:
            pyautogui.press(value)
        elif input_type == "hotkey":
            keys = value if isinstance(value, list) else str(value or "").split("+")
            if not keys or len(keys) > 5 or not all(isinstance(k, str) and len(k) <= 32 for k in keys):
                raise ValueError("Invalid hotkey")
            pyautogui.hotkey(*keys)
        else:
            raise ValueError("Unsupported keyboard input")
        return _result(True, "Keyboard input completed")

    if command == "quick_action":
        action = str(payload.get("action", ""))
        if action == "show_desktop":
            _require_desktop()
            pyautogui.hotkey("win", "d")
        elif action == "open_task_manager":
            _require_desktop()
            pyautogui.hotkey("ctrl", "shift", "esc")
        elif action == "open_explorer":
            _require_desktop()
            pyautogui.hotkey("win", "e")
        elif action == "close_active_window":
            _require_desktop()
            pyautogui.hotkey("alt", "f4")
        elif action in {"volume_up", "volume_down", "volume_mute"}:
            _require_desktop()
            key = {"volume_up": "volumeup", "volume_down": "volumedown", "volume_mute": "volumemute"}[action]
            pyautogui.press(key, presses=3 if action != "volume_mute" else 1)
        elif action == "open_url":
            webbrowser.open(_safe_url(payload.get("url")))
        elif action == "capture_screen":
            _require_desktop()
            image = pyautogui.screenshot()
            image.thumbnail((1280, 720))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=65)
            return _result(True, "Screenshot captured", base64.b64encode(buffer.getvalue()).decode())
        elif action == "clipboard_inject":
            if not ALLOW_DANGEROUS:
                raise PermissionError("Clipboard injection is disabled by policy")
            text = str(payload.get("text", ""))
            if not text or len(text) > 4000:
                raise ValueError("Clipboard text is empty or too long")
            import pyperclip
            pyperclip.copy(text)
        elif action == "lock_workstation":
            if not ALLOW_DANGEROUS or os.name != "nt":
                raise PermissionError("Workstation lock is disabled by policy")
            import ctypes
            ctypes.windll.user32.LockWorkStation()
        elif action == "kill_distracting_app":
            if not ALLOW_DANGEROUS or os.name != "nt":
                raise PermissionError("Process control is disabled by policy")
            app_name = str(payload.get("appName", "")).strip().lower()
            if not app_name or app_name not in ALLOWED_PROCESSES:
                raise PermissionError("Process is not in DESKTOP_AGENT_ALLOWED_PROCESSES")
            subprocess.run(["taskkill", "/F", "/IM", app_name], check=False, timeout=10)
        elif action == "windows_alert":
            if os.name != "nt":
                raise RuntimeError("Windows alert is only supported on Windows")
            import ctypes
            message = str(payload.get("message", ""))[:1000]
            ctypes.windll.user32.MessageBoxW(0, message, "WeWatch Alert", 0x40000 | 0x30)
        elif action == "system_telemetry":
            if os.name != "nt":
                raise RuntimeError("Windows telemetry is only supported on Windows")
            import ctypes
            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            total = round(status.ullTotalPhys / (1024**3), 1)
            available = round(status.ullAvailPhys / (1024**3), 1)
            return _result(True, f"RAM: {status.dwMemoryLoad}% used ({available}GB free of {total}GB)")
        else:
            raise ValueError("Unsupported desktop action")
        return _result(True, f"Action {action} completed")

    raise ValueError("Unsupported agent command")


sio = socketio.Client(reconnection=True, logger=False, engineio_logger=False)
_seen_command_ids = deque(maxlen=512)
_seen_command_lock = threading.Lock()
_presence_stop = threading.Event()
_presence_thread = None


def _claim_command(data):
    """Accept only fresh, non-replayed commands from the signaling server."""
    request_id = data.get("request_id")
    if not isinstance(request_id, str) or not request_id or len(request_id) > 64:
        raise ValueError("Invalid command request id")
    try:
        expires_at = float(data.get("expires_at", 0))
    except (TypeError, ValueError):
        raise ValueError("Invalid command expiry")
    if expires_at <= time.time():
        raise ValueError("Command expired")
    with _seen_command_lock:
        if request_id in _seen_command_ids:
            raise ValueError("Duplicate command request")
        _seen_command_ids.append(request_id)
    return request_id


@sio.event
def connect():
    global _presence_thread
    logging.info("Desktop agent connected to %s", SERVER_URL)
    _presence_stop.clear()
    sio.emit("join", {
        "role": "agent",
        "identity": AGENT_IDENTITY,
        "name": f"Desktop Agent ({AGENT_IDENTITY})",
        "target_identity": TARGET_IDENTITY,
        "agent_token": AGENT_TOKEN,
    })
    if _presence_thread is None or not _presence_thread.is_alive():
        _presence_thread = threading.Thread(target=_presence_loop, daemon=True)
        _presence_thread.start()


@sio.event
def disconnect():
    _presence_stop.set()
    logging.warning("Desktop agent disconnected")


def _presence_loop():
    while not _presence_stop.wait(60):
        if sio.connected:
            sio.emit("presence_ping")


@sio.on("desktop_command")
def on_desktop_command(data):
    if not isinstance(data, dict):
        return
    request_id = data.get("request_id", "")
    try:
        request_id = _claim_command(data)
        result = execute_command(data.get("command", ""), data.get("payload", {}))
    except Exception as exc:
        logging.exception("Desktop command failed: %s", exc)
        result = _result(False, str(exc))
    result.update({"request_id": request_id, "reply_to": data.get("reply_to")})
    sio.emit("agent_action_result", result)


def main():
    if not AGENT_TOKEN:
        raise SystemExit("DESKTOP_AGENT_TOKEN is required")
    if not TARGET_IDENTITY:
        raise SystemExit("DESKTOP_AGENT_TARGET_IDENTITY is required")
    sio.connect(SERVER_URL, transports=["websocket"], wait_timeout=15)
    sio.wait()


if __name__ == "__main__":
    main()