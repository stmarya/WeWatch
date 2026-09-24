import cv2
import mediapipe as mp
import math
import numpy as np
import face_recognition
import os
import time
import threading
import pyautogui
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load Env
load_dotenv()
pyautogui.FAILSAFE = False

# Modul Internal
from utils.helpers import is_thumbs_up, is_v_sign, calculate_bpm, overlay_transparent, calculate_angle, is_i_love_you, is_hello, is_ok, get_gaze_direction
from services.voice import speak
from services.telegram_bot import send_telegram_alert, GALLERY_FOLDER
from services.database import insert_mood, log_clock_in, update_work_time
from core.ai_models import AIModelManager
from utils.security import Cooldown, MajorityVote, safe_face_name

FEATURES = {
    'kantuk': True,
    'kacamata': False,
    'mouse': False,
    'identitas': False,
    'hands': False,
    'blur': False,
    'postur': False,
    'keamanan': False,
    'rppg': False,
    'bosskey': False,
    'object': False,
    'trainer': False,
    'sign_language': False,
    'gaze_tracking': False,
    'liveness': False,
    'virtual_keyboard': False,
    'voice_command': False,
    'tryon_kumis': False,
    'tryon_topi': False,
    'music_player': False,
    'produktivitas': False
}

STATUS = {
    'identitas': '-',
    'ekspresi': '-',
    'kantuk': False,
    'postur': False,
    'bpm': 0,
    'reps': 0,
    'sign_text': '-',
    'gaze_direction': '-',
    'liveness': 'OFF',
    'keyboard_text': '',
    'last_command': '-',
    'kehadiran': 'AT DESK',
    'main_hp': 'AMAN',
    'status_kerja': 'Kerja',
    'active_user': '-',
    'work_duration': 0
}

def draw_hud_face_reticle(image, left, top, right, bottom, name):
    """Draws a sleek, modern HUD corner bracket reticle and translucent pill badge."""
    is_known = (name != "Tidak Dikenal" and name != "Unknown" and name != "OFF" and name != "-")
    # Modern aesthetic colors: Emerald Green for verified, Soft Crimson/Amber for unknown
    accent_color = (83, 201, 129) if is_known else (72, 85, 234) # BGR
    
    w = right - left
    h = bottom - top
    if w <= 10 or h <= 10:
        return
    corner_len = max(12, min(24, int(min(w, h) * 0.22)))
    
    # 1. Subtle semi-transparent bounding outline (alpha 0.25)
    overlay = image.copy()
    cv2.rectangle(overlay, (left, top), (right, bottom), accent_color, 1, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.25, image, 0.75, 0, image)
    
    # 2. Sleek Corner Reticle Brackets (Thickness 2, anti-aliased)
    thick = 2
    # Top-Left
    cv2.line(image, (left, top), (left + corner_len, top), accent_color, thick, cv2.LINE_AA)
    cv2.line(image, (left, top), (left, top + corner_len), accent_color, thick, cv2.LINE_AA)
    # Top-Right
    cv2.line(image, (right, top), (right - corner_len, top), accent_color, thick, cv2.LINE_AA)
    cv2.line(image, (right, top), (right, top + corner_len), accent_color, thick, cv2.LINE_AA)
    # Bottom-Left
    cv2.line(image, (left, bottom), (left + corner_len, bottom), accent_color, thick, cv2.LINE_AA)
    cv2.line(image, (left, bottom), (left, bottom - corner_len), accent_color, thick, cv2.LINE_AA)
    # Bottom-Right
    cv2.line(image, (right, bottom), (right - corner_len, bottom), accent_color, thick, cv2.LINE_AA)
    cv2.line(image, (right, bottom), (right, bottom - corner_len), accent_color, thick, cv2.LINE_AA)
    
    # 3. Floating Glassmorphic Pill Badge
    tag_text = f" {name} " if is_known else " Unknown "
    font = cv2.FONT_HERSHEY_DUPLEX
    font_scale = 0.52
    text_thick = 1
    (text_w, text_h), baseline = cv2.getTextSize(tag_text, font, font_scale, text_thick)
    
    pill_w = text_w + 22
    pill_h = text_h + 12
    pill_x = left + (w - pill_w) // 2
    pill_y = max(8, top - pill_h - 6)
    
    # Translucent Dark Background Pill
    overlay_pill = image.copy()
    cv2.rectangle(overlay_pill, (pill_x, pill_y), (pill_x + pill_w, pill_y + pill_h), (20, 21, 24), -1)
    cv2.addWeighted(overlay_pill, 0.75, image, 0.25, 0, image)
    
    # Thin accent border around pill
    cv2.rectangle(image, (pill_x, pill_y), (pill_x + pill_w, pill_y + pill_h), accent_color, 1, cv2.LINE_AA)
    
    # Status Dot Indicator inside pill
    dot_x = pill_x + 9
    dot_y = pill_y + pill_h // 2
    cv2.circle(image, (dot_x, dot_y), 3, accent_color, -1, cv2.LINE_AA)
    
    # Typography
    cv2.putText(image, tag_text, (pill_x + 14, pill_y + pill_h - 4), font, font_scale, (255, 255, 255), text_thick, cv2.LINE_AA)

class AICamera:
    def __init__(self, features, status):
        self.features = features
        self.status = status
        self.frame_bytes = None
        self.frame_rgb = None
        self.capture_rgb = None
        self.raw_frame = None
        self.running = True
        self._frame_lock = threading.Lock()
        self._face_lock = threading.RLock()
        self._frame_sequence = 0
        self._next_encode_at = 0.0
        self._identity_vote = MajorityVote(size=5)
        self._alert_cooldown = Cooldown(seconds=8)
        self.base_dir = Path(__file__).resolve().parent

        # Inisialisasi Hardware Kamera dengan Buffer 1 untuk Zero Latency
        self.video = cv2.VideoCapture(0, cv2.CAP_DSHOW if os.name == 'nt' else cv2.CAP_ANY)
        self.video.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.video.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.video.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.video.set(cv2.CAP_PROP_FPS, 30)

        # Inisialisasi Model AI Terpusat
        self.ai = AIModelManager()

        # Cache deteksi untuk rendering mulus tanpa stutter
        self.last_face_landmarks = []
        self.last_face_data = []
        self.face_id_busy = False
        self.last_detected_objects = []
        self.last_hand_landmarks = []
        self.last_pose_landmarks = None
        self.cached_blur_mask = None

        # Placeholder frame saat kamera sedang pemanasan
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(blank, "Starting Camera...", (180, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        _, b = cv2.imencode('.jpg', blank)
        self.frame_bytes = b.tobytes()

        # Thread 1: Hardware Frame Grabber (mencegah OpenCV buffer queue lag)
        threading.Thread(target=self._safe_grabber_loop, daemon=True).start()

        # Thread 2: Video Processing & AI Pipeline
        threading.Thread(target=self._safe_update, daemon=True).start()
        logging.info("AICamera Turbo Pipeline Initialized Successfully.")

    def _safe_grabber_loop(self):
        try:
            self._grabber_loop()
        except Exception:
            logging.exception("Camera grabber stopped unexpectedly")
            self.running = False

    def _safe_update(self):
        try:
            self.update()
        except Exception:
            logging.exception("AI processing loop stopped unexpectedly")
            self.running = False

    def _grabber_loop(self):
        """Thread terpisah khusus membaca hardware webcam tanpa delay buffer."""
        while self.running:
            success, frame = self.video.read()
            if success and frame is not None:
                with self._frame_lock:
                    self.raw_frame = frame
            else:
                time.sleep(0.005)

    def _async_face_id(self, rgb_image, known_box=None):
        """Thread terpisah untuk ekstraksi dlib face_encodings dengan presisi tinggi tanpa lag."""
        try:
            face_locs = []
            if known_box:
                face_locs = [known_box]
            if not face_locs:
                small_rgb = cv2.resize(rgb_image, (0, 0), fx=0.5, fy=0.5)
                raw_locs = face_recognition.face_locations(small_rgb)
                face_locs = [(t * 2, r * 2, b * 2, l * 2) for (t, r, b, l) in raw_locs]

            if not face_locs:
                self.status['identitas'] = "Tidak Dikenal"
                return

            face_encs = face_recognition.face_encodings(rgb_image, face_locs, num_jitters=1)
            # Fallback jika crop known_box gagal menghasilkan encodings
            if not face_encs and known_box:
                small_rgb = cv2.resize(rgb_image, (0, 0), fx=0.5, fy=0.5)
                raw_locs = face_recognition.face_locations(small_rgb)
                face_locs = [(t * 2, r * 2, b * 2, l * 2) for (t, r, b, l) in raw_locs]
                if face_locs:
                    face_encs = face_recognition.face_encodings(rgb_image, face_locs, num_jitters=1)

            if not face_encs:
                self.status['identitas'] = "Tidak Dikenal"
                return

            new_face_data = []
            current_name = "Tidak Dikenal"
            with self._face_lock:
                known_encodings = list(self.ai.known_face_encodings)
                known_names = list(self.ai.known_face_names)

            if known_encodings:
                for (top, right, bottom, left), enc in zip(face_locs, face_encs):
                    face_distances = face_recognition.face_distance(known_encodings, enc)
                    best_match_idx = int(np.argmin(face_distances))
                    name = "Tidak Dikenal"
                    # A stricter threshold reduces false positives. The margin
                    # check also rejects ambiguous matches between similar faces.
                    sorted_distances = np.sort(face_distances)
                    best_distance = float(sorted_distances[0])
                    margin = float(sorted_distances[1] - sorted_distances[0]) if len(sorted_distances) > 1 else 1.0
                    if best_distance <= 0.54 and margin >= 0.035:
                        name = known_names[best_match_idx]
                        current_name = name
                    new_face_data.append((name, top, right, bottom, left))
            else:
                for (top, right, bottom, left) in face_locs:
                    new_face_data.append(("Tidak Dikenal", top, right, bottom, left))

            self.last_face_data = new_face_data
            stable_name = self._identity_vote.add(current_name)
            self.status['identitas'] = stable_name
            if current_name != "Tidak Dikenal" and self.status['active_user'] != current_name:
                self.status['active_user'] = current_name
                log_clock_in(current_name)
        except Exception as e:
            logging.debug(f"Async Face ID error: {e}")
        finally:
            self.face_id_busy = False

    def update(self):
        mata_tertutup_frames = 0
        frame_count = 0
        thumbs_up_frames = 0
        v_sign_frames = 0
        rppg_buffer = []
        last_announced_object = ""
        last_announce_time = 0
        trainer_state = None
        sign_frames = 0
        current_sign = ""
        last_announced_sign = ""

        liveness_verified = False
        face_missing_frames = 0

        hp_tercyduk_frames = 0
        last_hp_alert = 0

        last_work_update_time = time.time()
        away_start_time = None
        alarm_triggered = False

        keyboard_layout = [
            ['A', 'B', 'C'],
            ['D', 'E', 'F'],
            ['SPC', 'CLR', 'ENT']
        ]
        key_w, key_h, gap = 80, 80, 20
        start_x, start_y = 30, 30
        hovered_key = None
        keyboard_hover_frames = 0

        while self.running:
            with self._frame_lock:
                if self.raw_frame is None:
                    raw_frame = None
                else:
                    raw_frame = self.raw_frame.copy()
            if raw_frame is None:
                time.sleep(0.01)
                continue

            # Ambil frame terbaru dan flip
            image = cv2.flip(raw_frame, 1)
            h_img, w_img, _ = image.shape
            # Keep a clean copy for face enrollment; the display frame receives
            # overlays later in this loop.
            capture_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
            frame_count += 1

            # -------------------------------------------------------------
            # 1. OPTIMIZED BACKGROUND BLUR (Downscaled Bokeh)
            # -------------------------------------------------------------
            if self.features['blur']:
                try:
                    if frame_count % 3 == 0 or self.cached_blur_mask is None:
                        seg_result = self.ai.segmenter.segment(mp_image)
                        mask = seg_result.category_mask.numpy_view() > 0.1
                        self.cached_blur_mask = np.dstack((mask, mask, mask))

                    if self.cached_blur_mask is not None:
                        # Super fast downscaled Gaussian blur (~3ms vs ~60ms)
                        small_img = cv2.resize(image, (w_img // 4, h_img // 4))
                        small_blur = cv2.GaussianBlur(small_img, (21, 21), 0)
                        blurred_bg = cv2.resize(small_blur, (w_img, h_img), interpolation=cv2.INTER_LINEAR)
                        image = np.where(self.cached_blur_mask, image, blurred_bg)
                except Exception as e:
                    logging.debug(f"Blur error: {e}")

            # -------------------------------------------------------------
            # 2. ROUND-ROBIN SCHEDULING UNTUK INFERENSI AI BERAT
            # -------------------------------------------------------------
            # Frame genap (0, 2, 4...) -> Face Landmarker
            # Frame ganjil (1, 3, 5...) -> Pose, Hands, atau Objects (staggered)

            run_face_ai = (frame_count % 2 == 0)
            run_hand_ai = (frame_count % 2 == 1) and (self.features['hands'] or self.features['bosskey'] or self.features['sign_language'] or self.features['virtual_keyboard'])
            run_pose_ai = (frame_count % 3 == 1) and (self.features['postur'] or self.features['trainer'])
            run_obj_ai = (frame_count % 3 == 2) and (self.features.get('object', False) or self.features.get('produktivitas', False))

            # -------------------------------------------------------------
            # 3. OBJECT DETECTOR (Anti-Phone & Bounding Boxes)
            # -------------------------------------------------------------
            if run_obj_ai:
                try:
                    obj_result = self.ai.object_detector.detect(mp_image)
                    self.last_detected_objects = []
                    for obj in obj_result.detections:
                        bbox = obj.bounding_box
                        name = obj.categories[0].category_name
                        self.last_detected_objects.append({'name': name, 'bbox': bbox})
                except Exception as e:
                    logging.debug(f"Object error: {e}")

            # Render Object BBoxes & Cek HP
            if self.features.get('object', False):
                for obj in self.last_detected_objects:
                    bbox = obj['bbox']
                    name = obj['name']
                    cv2.rectangle(image, (bbox.origin_x, bbox.origin_y), (bbox.origin_x + bbox.width, bbox.origin_y + bbox.height), (255, 0, 255), 2)
                    cv2.putText(image, name, (bbox.origin_x, bbox.origin_y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 255), 2)

            if self.features.get('produktivitas', False):
                is_holding_hp = any(obj['name'] == 'cell phone' for obj in self.last_detected_objects)
                if is_holding_hp:
                    hp_tercyduk_frames += 1
                    if hp_tercyduk_frames > 10:
                        self.status['main_hp'] = "TERCYDUK"
                        if time.time() - last_hp_alert > 10:
                            send_telegram_alert(image, "📱 ALERT: User ketahuan bermain HP saat jam kerja!", save_as="main_hp")
                            if self._alert_cooldown.ready("main_hp_voice"):
                                speak("Tuan, berhentilah bermain ponsel dan kembalilah bekerja.")
                            last_hp_alert = time.time()
                else:
                    hp_tercyduk_frames = 0
                    self.status['main_hp'] = "AMAN"

            # -------------------------------------------------------------
            # 4. FACE IDENTITAS & SLEEK HUD RETICLE
            # -------------------------------------------------------------
            known_box = None
            if self.last_face_landmarks:
                lm = self.last_face_landmarks[0]
                xs = [p.x for p in lm]
                ys = [p.y for p in lm]
                w_box = max(xs) - min(xs)
                h_box = max(ys) - min(ys)
                pad_x = w_box * 0.15
                pad_y = h_box * 0.20
                l = max(0, int((min(xs) - pad_x) * w_img))
                r = min(w_img - 1, int((max(xs) + pad_x) * w_img))
                t = max(0, int((min(ys) - pad_y) * h_img))
                b = min(h_img - 1, int((max(ys) + pad_y) * h_img))
                if r > l + 20 and b > t + 20:
                    known_box = (t, r, b, l)

            if self.features['identitas'] and self.ai.known_face_encodings:
                if frame_count % 15 == 0 and not self.face_id_busy:
                    self.face_id_busy = True
                    threading.Thread(target=self._async_face_id, args=(rgb_image.copy(), known_box), daemon=True).start()

                # Render Sleek HUD Corner Reticle & Glassmorphism Badge (bukan kotak tebal kaku)
                if known_box:
                    t, r, b, l = known_box
                    draw_hud_face_reticle(image, l, t, r, b, self.status['identitas'])
                elif self.last_face_data:
                    for (name, top, right, bottom, left) in self.last_face_data:
                        draw_hud_face_reticle(image, left, top, right, bottom, name)
            else:
                self.status['identitas'] = "OFF"
                self.last_face_data = []

            if (
                self.features['keamanan']
                and self.status['identitas'] == "Tidak Dikenal"
                and self.last_face_landmarks
                and self.status['kehadiran'] == "AT DESK"
            ):
                send_telegram_alert(image, "🚨 ALERT: Seseorang yang tidak dikenal terdeteksi di kamera Anda!", save_as="penyusup")
                if self._alert_cooldown.ready("penyusup_voice"):
                    speak("Awas, penyusup terdeteksi.")

            # -------------------------------------------------------------
            # 5. POSE DETECTOR (Postur & AI Trainer)
            # -------------------------------------------------------------
            if run_pose_ai:
                try:
                    pose_result = self.ai.pose_detector.detect(mp_image)
                    if pose_result.pose_landmarks:
                        self.last_pose_landmarks = pose_result.pose_landmarks[0]
                    else:
                        self.last_pose_landmarks = None
                except Exception as e:
                    logging.debug(f"Pose error: {e}")

            if self.last_pose_landmarks:
                pose = self.last_pose_landmarks
                # Postur
                if self.features['postur']:
                    nose_y, shoulder_y = pose[0].y, (pose[11].y + pose[12].y) / 2
                    if shoulder_y - nose_y < 0.18:
                        self.status['postur'] = True
                        if self._alert_cooldown.ready("postur_voice"):
                            speak("Tuan, perbaiki postur tubuh Anda.")
                    else:
                        self.status['postur'] = False

                # AI Trainer
                if self.features['trainer']:
                    shoulder = [pose[12].x, pose[12].y]
                    elbow = [pose[14].x, pose[14].y]
                    wrist = [pose[16].x, pose[16].y]
                    angle = calculate_angle(shoulder, elbow, wrist)

                    ex, ey = int(elbow[0] * w_img), int(elbow[1] * h_img)
                    cv2.putText(image, str(int(angle)), (ex - 20, ey - 20), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)

                    if angle > 160:
                        trainer_state = "TURUN"
                    if angle < 40 and trainer_state == "TURUN":
                        trainer_state = "NAIK"
                        self.status['reps'] += 1
                        speak(f"{self.status['reps']}")

                    cv2.rectangle(image, (0, 0), (225, 73), (245, 117, 16), -1)
                    cv2.putText(image, 'REPS', (15, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
                    cv2.putText(image, str(self.status['reps']), (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 2, cv2.LINE_AA)
                    cv2.putText(image, 'STAGE', (100, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
                    cv2.putText(image, str(trainer_state), (100, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)

            # -------------------------------------------------------------
            # 6. FACE LANDMARKER (Ekspresi, Drowsiness, Gaze, Liveness, AR)
            # -------------------------------------------------------------
            detection_result = None
            if run_face_ai:
                try:
                    detection_result = self.ai.face_detector.detect(mp_image)
                    if detection_result and detection_result.face_landmarks:
                        self.last_face_landmarks = detection_result.face_landmarks
                    else:
                        self.last_face_landmarks = []
                except Exception as exc:
                    logging.debug("Face landmark detection failed: %s", exc)
                    self.last_face_landmarks = []

            if run_face_ai:
                if not detection_result or not detection_result.face_landmarks:
                    face_missing_frames += 1
                    if face_missing_frames > 15:
                        liveness_verified = False
                        self.status['liveness'] = "OFF"
                    if face_missing_frames > 75:  # ~5 detik
                        self.status['kehadiran'] = "AWAY"
                        if away_start_time is None:
                            away_start_time = time.time()
                        elif time.time() - away_start_time > 15 and not alarm_triggered:
                            alarm_triggered = True
                            if self._alert_cooldown.ready("away_voice"):
                                speak("Peringatan, karyawan meninggalkan meja kerja terlalu lama.")
                            send_telegram_alert(image, f"🚨 ALERT: Karyawan {self.status['active_user']} meninggalkan meja kerja lebih dari 15 detik!", save_as="away_alarm")
                else:
                    self.status['kehadiran'] = "AT DESK"
                    away_start_time = None
                    alarm_triggered = False

                if detection_result and detection_result.face_blendshapes:
                    face_missing_frames = 0
                    for b in detection_result.face_blendshapes:
                        smile = sum(c.score for c in b if c.category_name in ['mouthSmileLeft', 'mouthSmileRight'])/2
                        blink = sum(c.score for c in b if c.category_name in ['eyeBlinkLeft', 'eyeBlinkRight'])/2
                        jaw = next((c.score for c in b if c.category_name == 'jawOpen'), 0)

                        emosi = "Netral"
                        if smile > 0.5: emosi = "Senyum"
                        elif jaw > 0.4: emosi = "Terkejut"
                        elif blink > 0.5: emosi = "Mata Tertutup"
                        self.status['ekspresi'] = emosi

                        # Async mood log agar tidak lock SQLite
                        if frame_count % 30 == 0:
                            threading.Thread(target=insert_mood, args=(emosi,), daemon=True).start()

                        if blink > 0.5: mata_tertutup_frames += 1
                        else: mata_tertutup_frames = 0

                        self.status['kantuk'] = False
                        if self.features['kantuk'] and mata_tertutup_frames >= 15:
                            self.status['kantuk'] = True
                            send_telegram_alert(image, "😴 ALERT: Anda terdeteksi mengantuk!", save_as="kantuk")
                            if self._alert_cooldown.ready("kantuk_voice"):
                                speak("Awas, Anda mengantuk. Segera bangun.")

                        # Liveness
                        if self.features['liveness']:
                            if blink > 0.4 or jaw > 0.4:
                                liveness_verified = True

                            if liveness_verified:
                                self.status['liveness'] = "PASSED"
                            else:
                                self.status['liveness'] = "PENDING"
                        else:
                            self.status['liveness'] = "OFF"

            # Render Face AR & Overlays setiap frame menggunakan self.last_face_landmarks
            if self.last_face_landmarks:
                face_landmarks = self.last_face_landmarks[0]
                if self.features['kacamata'] and self.ai.kacamata_img is not None and len(face_landmarks) >= 478:
                    rx, ry = int(face_landmarks[468].x * w_img), int(face_landmarks[468].y * h_img)
                    lx, ly = int(face_landmarks[473].x * w_img), int(face_landmarks[473].y * h_img)
                    dist = math.hypot(lx - rx, ly - ry)
                    if dist > 0:
                        scale = 2.3 * dist / self.ai.kacamata_img.shape[1]
                        kw, kh = int(self.ai.kacamata_img.shape[1] * scale), int(self.ai.kacamata_img.shape[0] * scale)
                        if kw > 0 and kh > 0:
                            k_res = cv2.resize(self.ai.kacamata_img, (kw, kh))
                            cx, cy = int((rx + lx) / 2), int((ry + ly) / 2)
                            image = overlay_transparent(image, k_res, cx - kw // 2, cy - kh // 2)

                if self.features.get('tryon_kumis', False) and self.ai.mustache_img is not None and len(face_landmarks) >= 478:
                    mx, my = int(face_landmarks[164].x * w_img), int(face_landmarks[164].y * h_img)
                    lx, ly = int(face_landmarks[292].x * w_img), int(face_landmarks[292].y * h_img)
                    rx, ry = int(face_landmarks[62].x * w_img), int(face_landmarks[62].y * h_img)
                    dist = math.hypot(lx - rx, ly - ry)
                    if dist > 0:
                        scale = 1.2 * dist / self.ai.mustache_img.shape[1]
                        mw, mh = int(self.ai.mustache_img.shape[1] * scale), int(self.ai.mustache_img.shape[0] * scale)
                        if mw > 0 and mh > 0:
                            m_res = cv2.resize(self.ai.mustache_img, (mw, mh))
                            image = overlay_transparent(image, m_res, mx - mw // 2, my - mh // 2)

                if self.features.get('tryon_topi', False) and self.ai.tophat_img is not None and len(face_landmarks) >= 478:
                    tx, ty = int(face_landmarks[10].x * w_img), int(face_landmarks[10].y * h_img)
                    lx, ly = int(face_landmarks[234].x * w_img), int(face_landmarks[234].y * h_img)
                    rx, ry = int(face_landmarks[454].x * w_img), int(face_landmarks[454].y * h_img)
                    dist = math.hypot(lx - rx, ly - ry)
                    if dist > 0:
                        scale = 1.5 * dist / self.ai.tophat_img.shape[1]
                        tw, th = int(self.ai.tophat_img.shape[1] * scale), int(self.ai.tophat_img.shape[0] * scale)
                        if tw > 0 and th > 0:
                            t_res = cv2.resize(self.ai.tophat_img, (tw, th))
                            image = overlay_transparent(image, t_res, tx - tw // 2, ty - th + int(th*0.2))

                # Gaze
                if self.features['gaze_tracking'] and len(face_landmarks) >= 478:
                    iris_center = face_landmarks[468]
                    eye_left = face_landmarks[33]
                    eye_right = face_landmarks[133]
                    gaze = get_gaze_direction(iris_center, eye_left, eye_right)
                    self.status['gaze_direction'] = gaze
                    cv2.putText(image, f"MATA: {gaze}", (20, h_img - 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

                # rPPG
                if self.features['rppg']:
                    fx, fy = int(face_landmarks[10].x * w_img), int(face_landmarks[10].y * h_img)
                    if 0 < fy-20 and fy+20 < h_img and 0 < fx-20 and fx+20 < w_img:
                        roi = rgb_image[fy-20:fy+20, fx-20:fx+20]
                        rppg_buffer.append(np.mean(roi[:, :, 1]))
                        if len(rppg_buffer) > 150: rppg_buffer.pop(0)
                        self.status['bpm'] = calculate_bpm(rppg_buffer, fps=15)

            # -------------------------------------------------------------
            # 7. HAND TRACKING (Gestur, Sign Language, Virtual Keyboard)
            # -------------------------------------------------------------
            if run_hand_ai:
                try:
                    hands_result = self.ai.hands_detector.detect(mp_image)
                    if hands_result.hand_landmarks:
                        self.last_hand_landmarks = hands_result.hand_landmarks
                    else:
                        self.last_hand_landmarks = []
                except Exception as e:
                    logging.debug(f"Hand error: {e}")

            if self.last_hand_landmarks:
                for hl in self.last_hand_landmarks:
                    # Bahasa Isyarat
                    if self.features['sign_language']:
                        detected_sign = ""
                        if is_i_love_you(hl): detected_sign = "I Love You"
                        elif is_ok(hl): detected_sign = "OK / Mengerti"
                        elif is_hello(hl): detected_sign = "Halo!"

                        if detected_sign:
                            if current_sign == detected_sign:
                                sign_frames += 1
                                if sign_frames > 10:
                                    self.status['sign_text'] = detected_sign
                                    cv2.putText(image, f"TERJEMAHAN: {detected_sign}", (20, h_img - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 0), 2)
                                    if last_announced_sign != detected_sign:
                                        speak(detected_sign)
                                        last_announced_sign = detected_sign
                            else:
                                current_sign = detected_sign
                                sign_frames = 0
                        else:
                            sign_frames = 0
                            last_announced_sign = ""

                    # Virtual Keyboard
                    if self.features['virtual_keyboard']:
                        ix, iy = int(hl[8].x * w_img), int(hl[8].y * h_img)
                        cv2.circle(image, (ix, iy), 12, (255, 0, 255), cv2.FILLED)
                        current_hover = None

                        for row_idx, row in enumerate(keyboard_layout):
                            for col_idx, key in enumerate(row):
                                kx = start_x + col_idx * (key_w + gap)
                                ky = start_y + row_idx * (key_h + gap)
                                is_hover = (kx < ix < kx + key_w) and (ky < iy < ky + key_h)
                                color = (200, 200, 200)
                                text_color = (0, 0, 0)

                                if is_hover:
                                    current_hover = key
                                    color = (0, 255, 255)
                                    prog = int((keyboard_hover_frames / 12.0) * key_w)
                                    cv2.rectangle(image, (kx, ky + key_h - 8), (kx + prog, ky + key_h), (0, 0, 255), cv2.FILLED)

                                overlay = image.copy()
                                cv2.rectangle(overlay, (kx, ky), (kx + key_w, ky + key_h), color, cv2.FILLED)
                                cv2.addWeighted(overlay, 0.6, image, 0.4, 0, image)
                                cv2.rectangle(image, (kx, ky), (kx + key_w, ky + key_h), (255, 255, 255), 2)

                                font_scale = 1 if len(key) > 1 else 1.3
                                tx = kx + 10 if len(key) > 1 else kx + 25
                                ty = ky + 50
                                cv2.putText(image, key, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_color, 2)

                        if current_hover:
                            if current_hover == hovered_key:
                                keyboard_hover_frames += 1
                                if keyboard_hover_frames > 12:
                                    if current_hover == 'SPC':
                                        self.status['keyboard_text'] += ' '
                                    elif current_hover == 'CLR':
                                        self.status['keyboard_text'] = ''
                                    elif current_hover == 'ENT':
                                        speak(f"Anda mengetik: {self.status['keyboard_text']}")
                                    else:
                                        self.status['keyboard_text'] += current_hover
                                        speak(current_hover)
                                    keyboard_hover_frames = 0
                            else:
                                hovered_key = current_hover
                                keyboard_hover_frames = 0
                        else:
                            hovered_key = None
                            keyboard_hover_frames = 0

                    # Thumbs Up & Boss Key
                    if self.features['hands']:
                        if is_thumbs_up(hl):
                            thumbs_up_frames += 1
                            if thumbs_up_frames > 15:
                                os.makedirs(GALLERY_FOLDER, exist_ok=True)
                                cv2.imwrite(os.path.join(GALLERY_FOLDER, f"screenshot_{int(time.time())}.jpg"), image)
                                thumbs_up_frames = -20
                        else:
                            if thumbs_up_frames > 0: thumbs_up_frames = 0
                            elif thumbs_up_frames < 0: thumbs_up_frames += 1

                    if self.features['bosskey']:
                        if is_v_sign(hl):
                            v_sign_frames += 1
                            if v_sign_frames > 15:
                                pyautogui.hotkey('win', 'd')
                                v_sign_frames = -30
                        else:
                            if v_sign_frames > 0: v_sign_frames = 0
                            elif v_sign_frames < 0: v_sign_frames += 1

                    # Smart Pointer
                    if self.features.get('object', False) and self.last_detected_objects:
                        ix, iy = int(hl[8].x * w_img), int(hl[8].y * h_img)
                        cv2.circle(image, (ix, iy), 10, (0, 255, 255), -1)
                        for obj in self.last_detected_objects:
                            bbox = obj['bbox']
                            if (bbox.origin_x < ix < bbox.origin_x + bbox.width) and (bbox.origin_y < iy < bbox.origin_y + bbox.height):
                                cv2.putText(image, "MENUNJUK: " + obj['name'].upper(), (20, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
                                if obj['name'] != last_announced_object or time.time() - last_announce_time > 5:
                                    last_announced_object = obj['name']
                                    last_announce_time = time.time()
                                    speak(f"Tuan, Anda sedang menunjuk {obj['name']}.")
                                break

            # -------------------------------------------------------------
            # 8. STATUS KERJA & WORK DURATION
            # -------------------------------------------------------------
            if self.features.get('produktivitas', False):
                if self.status['kehadiran'] == "AWAY":
                    self.status['status_kerja'] = "Meninggalkan Meja"
                elif self.status['main_hp'] == "TERCYDUK":
                    self.status['status_kerja'] = "Main HP"
                elif self.status['kantuk']:
                    self.status['status_kerja'] = "Mengantuk"
                elif self.status['postur']:
                    self.status['status_kerja'] = "Postur Buruk"
                else:
                    self.status['status_kerja'] = "Fokus Bekerja"
            else:
                self.status['status_kerja'] = "OFF"

            if self.features.get('produktivitas', False) and self.status['active_user'] != '-':
                if self.status['status_kerja'] == "Fokus Bekerja":
                    if time.time() - last_work_update_time >= 1.0:
                        update_work_time(self.status['active_user'], 1)
                        self.status['work_duration'] += 1
                        last_work_update_time = time.time()
                else:
                    last_work_update_time = time.time()

            # -------------------------------------------------------------
            # 9. ULTRA FAST JPEG ENCODING & STREAM CACHING (Quality 82)
            # -------------------------------------------------------------
            # Do not encode faster than the camera target FPS. This keeps the
            # AI loop responsive when several expensive features are enabled.
            now = time.monotonic()
            if now >= self._next_encode_at:
                ret, buffer = cv2.imencode(
                    '.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), 82]
                )
                if ret:
                    with self._frame_lock:
                        self.frame_bytes = buffer.tobytes()
                        self._frame_sequence += 1
                    self._next_encode_at = now + (1.0 / 30.0)

            with self._frame_lock:
                self.frame_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                self.capture_rgb = capture_rgb
            # Yield briefly so a fast CPU cannot starve the grabber and GUI.
            time.sleep(0.001)

    def register_face(self, name, rgb_frame=None):
        """Validate and atomically register exactly one face."""
        clean_name = safe_face_name(name)
        if rgb_frame is None:
            with self._frame_lock:
                rgb_frame = None if self.capture_rgb is None else self.capture_rgb.copy()
        if rgb_frame is None:
            return False, "Kamera belum siap."

        try:
            locations = face_recognition.face_locations(rgb_frame, model="hog")
            if len(locations) != 1:
                return False, "Pastikan tepat satu wajah terlihat jelas di kamera."
            encodings = face_recognition.face_encodings(rgb_frame, locations, num_jitters=2)
            if not encodings:
                return False, "Wajah tidak cukup jelas untuk didaftarkan."

            faces_dir = self.base_dir / "faces"
            faces_dir.mkdir(exist_ok=True)
            filepath = faces_dir / f"{clean_name}.jpg"
            temp_path = faces_dir / f".{clean_name}.tmp.jpg"
            bgr_frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)
            if not cv2.imwrite(str(temp_path), bgr_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95]):
                return False, "Gagal menyimpan foto wajah."
            os.replace(temp_path, filepath)

            with self._face_lock:
                # Re-registering a name replaces its old embedding instead of
                # adding duplicate entries that make matching ambiguous.
                kept = [
                    (encoding, existing_name)
                    for encoding, existing_name in zip(
                        self.ai.known_face_encodings, self.ai.known_face_names
                    )
                    if existing_name != clean_name
                ]
                self.ai.known_face_encodings = [item[0] for item in kept] + [encodings[0]]
                self.ai.known_face_names = [item[1] for item in kept] + [clean_name]
                self._identity_vote.clear()
            return True, f"Wajah '{clean_name}' berhasil didaftarkan."
        except Exception as exc:
            logging.error("Face registration failed: %s", exc)
            return False, "Registrasi wajah gagal. Periksa kamera dan coba lagi."

    def get_frame(self):
        with self._frame_lock:
            return self.frame_bytes

    def stop(self):
        self.running = False
        try:
            self.video.release()
        except Exception:
            pass
