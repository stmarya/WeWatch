import cv2
import mediapipe as mp
import math
import numpy as np
import pyautogui
import face_recognition
import os
import datetime
import customtkinter as ctk
from PIL import Image, ImageTk
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

pyautogui.FAILSAFE = False
screen_w, screen_h = pyautogui.size()

def overlay_transparent(background, overlay, x, y):
    bg_h, bg_w, _ = background.shape
    if x >= bg_w or y >= bg_h: return background
    h, w = overlay.shape[0], overlay.shape[1]
    if x + w > bg_w: w = bg_w - x; overlay = overlay[:, :w]
    if y + h > bg_h: h = bg_h - y; overlay = overlay[:h]
    if x < 0: overlay = overlay[:, -x:]; w += x; x = 0
    if y < 0: overlay = overlay[-y:, :]; h += y; y = 0
    if w <= 0 or h <= 0: return background
    overlay_image = overlay[..., :3]
    mask = overlay[..., 3:] / 255.0
    background[y:y+h, x:x+w] = (1.0 - mask) * background[y:y+h, x:x+w] + mask * overlay_image
    return background

def draw_hand_landmarks(image, hand_landmarks, w, h):
    connections = [
        (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), 
        (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), 
        (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20)
    ]
    points = {}
    for i, lm in enumerate(hand_landmarks):
        px, py = int(lm.x * w), int(lm.y * h)
        points[i] = (px, py)
        cv2.circle(image, (px, py), 4, (0, 0, 255), -1)
    for s, e in connections:
        if s in points and e in points:
            cv2.line(image, points[s], points[e], (0, 255, 0), 2)

def is_thumbs_up(hand_landmarks):
    # Logika Thumbs Up: Jempol di atas, jari lain mengepal ke bawah
    if (hand_landmarks[4].y < hand_landmarks[5].y and
        hand_landmarks[4].y < hand_landmarks[17].y and
        hand_landmarks[8].y > hand_landmarks[5].y and
        hand_landmarks[12].y > hand_landmarks[9].y):
        return True
    return False

class SuperFaceApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ULTIMATE AI - Keamanan & Analisis")
        self.geometry("1100x650")
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)
        
        self.video_frame = ctk.CTkFrame(self)
        self.video_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.video_label = ctk.CTkLabel(self.video_frame, text="Memuat AI Models...")
        self.video_label.pack(expand=True, fill="both")
        
        self.control_frame = ctk.CTkFrame(self, width=280)
        self.control_frame.grid(row=0, column=1, padx=10, pady=10, sticky="ns")
        
        ctk.CTkLabel(self.control_frame, text="Ultimate AI Panel", font=("Arial", 22, "bold")).pack(pady=10)
        
        self.var_kantuk = ctk.BooleanVar(value=True)
        self.var_kacamata = ctk.BooleanVar(value=False)
        self.var_mouse = ctk.BooleanVar(value=False)
        self.var_identitas = ctk.BooleanVar(value=False)
        self.var_hands = ctk.BooleanVar(value=False)
        self.var_blur = ctk.BooleanVar(value=False)
        self.var_postur = ctk.BooleanVar(value=False)
        self.var_keamanan = ctk.BooleanVar(value=False)
        
        ctk.CTkSwitch(self.control_frame, text="1. Pendeteksi Kantuk", variable=self.var_kantuk).pack(pady=8, padx=20, anchor="w")
        ctk.CTkSwitch(self.control_frame, text="2. Kacamata AR", variable=self.var_kacamata).pack(pady=8, padx=20, anchor="w")
        ctk.CTkSwitch(self.control_frame, text="3. Virtual Mouse", variable=self.var_mouse).pack(pady=8, padx=20, anchor="w")
        ctk.CTkSwitch(self.control_frame, text="4. Identitas Wajah", variable=self.var_identitas).pack(pady=8, padx=20, anchor="w")
        ctk.CTkSwitch(self.control_frame, text="5. Hand Gestures", variable=self.var_hands).pack(pady=8, padx=20, anchor="w")
        ctk.CTkSwitch(self.control_frame, text="6. Background Blur", variable=self.var_blur).pack(pady=8, padx=20, anchor="w")
        ctk.CTkSwitch(self.control_frame, text="7. Analisis Postur", variable=self.var_postur).pack(pady=8, padx=20, anchor="w")
        ctk.CTkSwitch(self.control_frame, text="8. Mode Keamanan (CCTV)", variable=self.var_keamanan).pack(pady=8, padx=20, anchor="w")

        # --- INIT MEDIA-PIPE MODELS ---
        self.face_detector = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path='face_landmarker.task'),
            output_face_blendshapes=True, output_facial_transformation_matrixes=True, num_faces=1))
        
        self.hands_detector = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path='hand_landmarker.task'), num_hands=2))
        
        self.pose_detector = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path='pose_landmarker.task')))
        
        self.segmenter = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
            base_options=python.BaseOptions(model_asset_path='selfie_segmenter.tflite'), output_category_mask=True))

        # --- IDENTITAS ---
        self.known_face_encodings = []
        self.known_face_names = []
        if os.path.exists('wajah_saya.jpg'):
            try:
                img_ref = face_recognition.load_image_file('wajah_saya.jpg')
                self.known_face_encodings.append(face_recognition.face_encodings(img_ref)[0])
                self.known_face_names.append("Altar")
            except: pass

        try: self.kacamata_img = cv2.imread('kacamata.png', cv2.IMREAD_UNCHANGED)
        except: self.kacamata_img = None
            
        self.is_blinking = False
        self.mata_tertutup_frames = 0
        self.frame_count = 0
        self.identitas_sekarang = "-"
        
        self.thumbs_up_frames = 0
        self.is_recording = False
        self.out_video = None
        
        self.cap = cv2.VideoCapture(0)
        self.update_video()

    def update_video(self):
        success, image = self.cap.read()
        if success:
            image = cv2.flip(image, 1)
            h_img, w_img, _ = image.shape
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
            
            # (6) BACKGROUND BLUR
            if self.var_blur.get():
                try:
                    seg_result = self.segmenter.segment(mp_image)
                    mask = seg_result.category_mask.numpy_view() > 0.1
                    mask_3d = np.dstack((mask, mask, mask))
                    blurred_bg = cv2.GaussianBlur(image, (55, 55), 0)
                    image = np.where(mask_3d, image, blurred_bg)
                except: pass

            status_gestur = ""
            # (5) HAND GESTURES
            if self.var_hands.get():
                try:
                    hands_result = self.hands_detector.detect(mp_image)
                    if hands_result.hand_landmarks:
                        for hl in hands_result.hand_landmarks:
                            draw_hand_landmarks(image, hl, w_img, h_img)
                            if is_thumbs_up(hl):
                                self.thumbs_up_frames += 1
                                if self.thumbs_up_frames > 15:
                                    cv2.imwrite(f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg", image)
                                    self.thumbs_up_frames = -20 # Cooldown
                                    status_gestur = "SCREENSHOT TERSIMPAN!"
                            else:
                                if self.thumbs_up_frames > 0: self.thumbs_up_frames = 0
                                elif self.thumbs_up_frames < 0: self.thumbs_up_frames += 1
                except: pass

            status_postur = ""
            # (7) ANALISIS POSTUR DUDUK
            if self.var_postur.get():
                try:
                    pose_result = self.pose_detector.detect(mp_image)
                    if pose_result.pose_landmarks:
                        pose = pose_result.pose_landmarks[0]
                        nose_y, shoulder_y = pose[0].y, (pose[11].y + pose[12].y) / 2
                        if shoulder_y - nose_y < 0.18: # Hidung terlalu dekat dengan bahu (membungkuk)
                            status_postur = "PERBAIKI POSTUR DUDUK!"
                except: pass

            # (4) IDENTITAS
            if self.var_identitas.get() and self.known_face_encodings:
                if self.frame_count % 5 == 0:
                    small_frame = cv2.resize(rgb_image, (0, 0), fx=0.25, fy=0.25)
                    face_locations = face_recognition.face_locations(small_frame)
                    face_encodings = face_recognition.face_encodings(small_frame, face_locations)
                    self.identitas_sekarang = "Tidak Dikenal"
                    for encoding in face_encodings:
                        matches = face_recognition.compare_faces(self.known_face_encodings, encoding, tolerance=0.5)
                        if True in matches:
                            self.identitas_sekarang = self.known_face_names[matches.index(True)]
            else: self.identitas_sekarang = "OFF"
            self.frame_count += 1

            # (8) MODE KEAMANAN SMART RECORDING
            status_rekam = ""
            if self.var_keamanan.get():
                if self.identitas_sekarang == "Tidak Dikenal":
                    if not self.is_recording:
                        fourcc = cv2.VideoWriter_fourcc(*'XVID')
                        self.out_video = cv2.VideoWriter(f"penyusup_{datetime.datetime.now().strftime('%H%M%S')}.avi", fourcc, 10.0, (w_img, h_img))
                        self.is_recording = True
                else:
                    if self.is_recording:
                        self.is_recording = False
                        self.out_video.release()
                        
                if self.is_recording:
                    self.out_video.write(image)
                    status_rekam = "MEREKAM PENYUSUP..."
                    cv2.rectangle(image, (0, 0), (w_img, h_img), (0, 0, 255), 10)
            else:
                if self.is_recording:
                    self.is_recording = False
                    self.out_video.release()

            # (1, 2, 3) FACE LANDMARKER
            ekspresi_text, arah_kepala, status_kantuk, klik_status = "-", "-", "", ""
            try: detection_result = self.face_detector.detect(mp_image)
            except: detection_result = None

            if detection_result and detection_result.face_blendshapes:
                for b in detection_result.face_blendshapes:
                    smile = sum(c.score for c in b if c.category_name in ['mouthSmileLeft', 'mouthSmileRight'])/2
                    blink = sum(c.score for c in b if c.category_name in ['eyeBlinkLeft', 'eyeBlinkRight'])/2
                    jaw = next((c.score for c in b if c.category_name == 'jawOpen'), 0)
                    if smile > 0.5: ekspresi_text = "Senyum"
                    elif jaw > 0.4: ekspresi_text = "Terkejut"
                    elif blink > 0.5: ekspresi_text = "Mata Tertutup"
                    
                    if self.var_mouse.get():
                        if blink > 0.6:
                            if not self.is_blinking: pyautogui.click(); self.is_blinking = True; klik_status = "KLIK!"
                        else: self.is_blinking = False
                    
                    if blink > 0.5: self.mata_tertutup_frames += 1
                    else: self.mata_tertutup_frames = 0
                    if self.var_kantuk.get() and self.mata_tertutup_frames >= 15: status_kantuk = "AWAS MENGANTUK!"

                for face_landmarks in detection_result.face_landmarks:
                    if self.var_mouse.get():
                        ujung_hidung = face_landmarks[1]
                        mx, my = int(ujung_hidung.x * screen_w), int(ujung_hidung.y * screen_h)
                        try:
                            mx = max(0, min(screen_w - 1, mx))
                            my = max(0, min(screen_h - 1, my))
                            pyautogui.moveTo(mx, my, duration=0.1)
                        except: pass
                        cv2.circle(image, (int(ujung_hidung.x * w_img), int(ujung_hidung.y * h_img)), 8, (0, 255, 0), -1)

                    if self.var_kacamata.get() and self.kacamata_img is not None and len(face_landmarks) >= 478:
                        rx, ry = int(face_landmarks[468].x * w_img), int(face_landmarks[468].y * h_img)
                        lx, ly = int(face_landmarks[473].x * w_img), int(face_landmarks[473].y * h_img)
                        dist = math.hypot(lx - rx, ly - ry)
                        if dist > 0:
                            scale = 2.3 * dist / self.kacamata_img.shape[1]
                            kw, kh = int(self.kacamata_img.shape[1] * scale), int(self.kacamata_img.shape[0] * scale)
                            if kw > 0 and kh > 0:
                                k_res = cv2.resize(self.kacamata_img, (kw, kh))
                                cx, cy = int((rx + lx) / 2), int((ry + ly) / 2)
                                image = overlay_transparent(image, k_res, cx - kw // 2, cy - kh // 2)

            # RENDER TEXT
            cv2.rectangle(image, (10, 10), (250, 150), (0, 0, 0), -1)
            cv2.putText(image, f'Ekspresi: {ekspresi_text}', (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            c_id = (0, 255, 0) if "Altar" in self.identitas_sekarang else (0, 0, 255)
            cv2.putText(image, f'ID: {self.identitas_sekarang}', (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, c_id, 2)
            
            if klik_status: cv2.putText(image, klik_status, (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 3)
            if status_kantuk: cv2.putText(image, status_kantuk, (int(w_img/2)-150, int(h_img/2)-50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 4)
            if status_postur: cv2.putText(image, status_postur, (int(w_img/2)-200, int(h_img/2)+50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 165, 255), 4)
            if status_gestur: cv2.putText(image, status_gestur, (20, 200), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 3)
            if status_rekam: cv2.putText(image, status_rekam, (int(w_img/2)-150, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

            img_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            img_pil = Image.fromarray(img_rgb)
            imgtk = ctk.CTkImage(light_image=img_pil, dark_image=img_pil, size=(w_img, h_img))
            
            self.video_label.configure(image=imgtk)
            self.video_label.image = imgtk

        self.after(10, self.update_video)

if __name__ == "__main__":
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    app = SuperFaceApp()
    app.mainloop()
