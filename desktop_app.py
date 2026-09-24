import customtkinter as ctk
from PIL import Image, ImageTk
import logging

from camera import FEATURES, STATUS
from app import camera

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class DesktopApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("The Ultimate Watcher - Desktop")
        self.geometry("1100x750")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        self.last_kantuk = False
        self.last_postur = False
        self.last_main_hp = False
        self.last_penyusup = False
        
        # Grid Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar (Controls) - SCROLLABLE
        self.sidebar = ctk.CTkScrollableFrame(self, width=320, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        self.logo_label = ctk.CTkLabel(self.sidebar, text="The Watcher V3", font=ctk.CTkFont(size=24, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")
        
        self.subtitle = ctk.CTkLabel(self.sidebar, text="AI Security Dashboard", font=ctk.CTkFont(size=12), text_color="gray")
        self.subtitle.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="w")
        
        self.reg_btn = ctk.CTkButton(self.sidebar, text="📸 Daftarkan Wajah", fg_color="#28a745", hover_color="#218838", command=self.register_face_desktop)
        self.reg_btn.grid(row=2, column=0, padx=20, pady=(0, 20), sticky="ew")

        self.switches = {}
        row_idx = 3
        
        # Grouped Features
        groups = {
            "💼 Productivity Tracker": [
                ("produktivitas", "Bos Virtual (Anti-HP & Fokus)")
            ],
            "🛡️ Security & Privacy": [
                ("kantuk", "Deteksi Kantuk"),
                ("identitas", "Deteksi Identitas (CCTV)"),
                ("keamanan", "Mode Keamanan Telegram"),
                ("liveness", "Liveness Detection"),
                ("blur", "Background Blur")
            ],
            "🪄 AR & Entertainment": [
                ("kacamata", "Try-On: Kacamata Hitam"),
                ("tryon_kumis", "Try-On: Kumis Pria"),
                ("tryon_topi", "Try-On: Topi Pesulap"),
                ("music_player", "🎵 Emotion Music Player")
            ],
            "✋ Gesture & AI Control": [
                ("hands", "Screenshot (Thumbs Up)"),
                ("bosskey", "Boss Key (Gestur V)"),
                ("object", "Smart Pointer & Object"),
                ("virtual_keyboard", "Virtual Keyboard (Hologram)"),
                ("voice_command", "Voice Command (Jarvis)")
            ],
            "📊 Health & Analytics": [
                ("postur", "Analisis Postur"),
                ("rppg", "Deteksi Detak Jantung (rPPG)"),
                ("trainer", "AI Trainer (Bicep Curls)"),
                ("sign_language", "Penerjemah Bahasa Isyarat"),
                ("gaze_tracking", "Gaze Tracking (Pelacakan Mata)")
            ]
        }
        
        for group_name, features in groups.items():
            grp_label = ctk.CTkLabel(self.sidebar, text=group_name, font=ctk.CTkFont(size=14, weight="bold"), text_color="#00d2ff")
            grp_label.grid(row=row_idx, column=0, padx=20, pady=(15, 5), sticky="w")
            row_idx += 1
            
            for key, label in features:
                switch = ctk.CTkSwitch(self.sidebar, text=label, command=lambda k=key: self.toggle_feature(k))
                switch.grid(row=row_idx, column=0, padx=30, pady=5, sticky="w")
                if FEATURES.get(key, False):
                    switch.select()
                self.switches[key] = switch
                row_idx += 1

        # Video Frame
        self.video_frame = ctk.CTkFrame(self)
        self.video_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.video_frame.grid_rowconfigure(0, weight=1)
        self.video_frame.grid_columnconfigure(0, weight=1)
        
        self.video_label = ctk.CTkLabel(self.video_frame, text="Kamera Memuat...")
        self.video_label.grid(row=0, column=0, sticky="nsew")
        
        # Status Bar di bawah Video
        self.status_bar = ctk.CTkFrame(self.video_frame, height=120)
        self.status_bar.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        
        self.status_bar.grid_columnconfigure((0,1,2,3,4), weight=1)
        
        self.stat_id = ctk.CTkLabel(self.status_bar, text="ID: -", font=ctk.CTkFont(size=13, weight="bold"))
        self.stat_id.grid(row=0, column=0, padx=10, pady=5)
        self.stat_mood = ctk.CTkLabel(self.status_bar, text="Emosi: -", font=ctk.CTkFont(size=13, weight="bold"))
        self.stat_mood.grid(row=0, column=1, padx=10, pady=5)
        self.stat_bpm = ctk.CTkLabel(self.status_bar, text="BPM: 0", font=ctk.CTkFont(size=13, weight="bold"), text_color="red")
        self.stat_bpm.grid(row=0, column=2, padx=10, pady=5)
        self.stat_kantuk = ctk.CTkLabel(self.status_bar, text="Kantuk: Aman", font=ctk.CTkFont(size=13, weight="bold"))
        self.stat_kantuk.grid(row=0, column=3, padx=10, pady=5)
        self.stat_postur = ctk.CTkLabel(self.status_bar, text="Postur: Tegak", font=ctk.CTkFont(size=13, weight="bold"))
        self.stat_postur.grid(row=0, column=4, padx=10, pady=5)
        
        self.stat_reps = ctk.CTkLabel(self.status_bar, text="Reps: 0", font=ctk.CTkFont(size=12))
        self.stat_reps.grid(row=1, column=0, padx=10, pady=5)
        self.stat_sign = ctk.CTkLabel(self.status_bar, text="Isyarat: -", font=ctk.CTkFont(size=12))
        self.stat_sign.grid(row=1, column=1, padx=10, pady=5)
        self.stat_gaze = ctk.CTkLabel(self.status_bar, text="Mata: -", font=ctk.CTkFont(size=12))
        self.stat_gaze.grid(row=1, column=2, padx=10, pady=5)
        self.stat_liveness = ctk.CTkLabel(self.status_bar, text="Liveness: OFF", font=ctk.CTkFont(size=12))
        self.stat_liveness.grid(row=1, column=3, padx=10, pady=5)
        self.stat_kerja = ctk.CTkLabel(self.status_bar, text="Kerja: OFF", font=ctk.CTkFont(size=12, weight="bold"))
        self.stat_kerja.grid(row=1, column=4, padx=10, pady=5)
        
        self.stat_user = ctk.CTkLabel(self.status_bar, text="User: -", font=ctk.CTkFont(size=12, weight="bold"), text_color="#28a745")
        self.stat_user.grid(row=1, column=5, padx=10, pady=5)
        self.stat_dur = ctk.CTkLabel(self.status_bar, text="Timer: 00:00:00", font=ctk.CTkFont(size=12, weight="bold"))
        self.stat_dur.grid(row=1, column=6, padx=10, pady=5)

        logging.info("Desktop GUI Initialized.")
        self.update_video()

    def on_close(self):
        """Release the webcam and stop background processing before exit."""
        try:
            camera.stop()
        finally:
            self.destroy()

    def show_toast(self, message):
        toast = ctk.CTkToplevel(self)
        # Tampilkan di pojok kanan atas aplikasi
        x = self.winfo_x() + self.winfo_width() - 320
        y = self.winfo_y() + 50
        toast.geometry(f"300x50+{x}+{y}")
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        lbl = ctk.CTkLabel(toast, text=message, font=ctk.CTkFont(weight="bold", size=14), fg_color="#ff4444", text_color="white", corner_radius=10)
        lbl.pack(expand=True, fill="both")
        self.after(3000, toast.destroy)

    def register_face_desktop(self):
        dialog = ctk.CTkInputDialog(text="Masukkan nama Anda untuk mendaftarkan wajah:", title="Face ID Registration")
        name = dialog.get_input()
        if name and name.strip():
            name = name.strip()
            success, message = camera.register_face(name)
            if success:
                logging.info(message)
                self.show_toast(message)
            else:
                logging.warning(message)
                self.show_toast(message)

    def toggle_feature(self, key):
        is_on = self.switches[key].get() == 1
        FEATURES[key] = is_on
        logging.info(f"[Desktop] Feature {key} set to {is_on}")

    def update_video(self):
        for key, switch in self.switches.items():
            current_ui_state = switch.get() == 1
            actual_state = FEATURES.get(key, False)
            if current_ui_state != actual_state:
                if actual_state:
                    switch.select()
                else:
                    switch.deselect()

        if camera.frame_rgb is not None:
            img = Image.fromarray(camera.frame_rgb)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
            self.video_label.configure(image=ctk_img, text="")
            self.video_label.image = ctk_img

        # Update Status Bar
        self.stat_id.configure(text=f"ID: {STATUS['identitas']}")
        self.stat_mood.configure(text=f"Emosi: {STATUS['ekspresi']}")
        self.stat_bpm.configure(text=f"BPM: {STATUS['bpm']}" if STATUS['bpm'] > 0 else "BPM: -")
        
        kantuk = STATUS['kantuk']
        self.stat_kantuk.configure(text=f"Kantuk: {'BAHAYA' if kantuk else 'Aman'}", text_color="red" if kantuk else "white")
        if kantuk and not self.last_kantuk:
            self.show_toast("AWAS MENGANTUK!")
        self.last_kantuk = kantuk
        
        postur = STATUS['postur']
        self.stat_postur.configure(text=f"Postur: {'MEMBUNGKUK' if postur else 'Tegak'}", text_color="red" if postur else "white")
        if postur and not self.last_postur:
            self.show_toast("PERBAIKI POSTUR DUDUK!")
        self.last_postur = postur
        
        self.stat_reps.configure(text=f"Reps: {STATUS['reps']}")
        self.stat_sign.configure(text=f"Isyarat: {STATUS['sign_text']}")
        self.stat_gaze.configure(text=f"Mata: {STATUS['gaze_direction']}")
        self.stat_liveness.configure(text=f"Liveness: {STATUS['liveness']}")
        
        status_kerja = STATUS['status_kerja']
        self.stat_kerja.configure(text=f"Kerja: {status_kerja}", text_color="red" if status_kerja == "Main HP" else ("green" if status_kerja == "Fokus Bekerja" else "white"))
        
        is_main_hp = (status_kerja == "Main HP" or STATUS['main_hp'] == "TERCYDUK")
        if is_main_hp and not self.last_main_hp:
            self.show_toast("KETAHUAN MAIN HP!")
        self.last_main_hp = is_main_hp
        
        is_penyusup = FEATURES.get('keamanan', False) and STATUS['identitas'] == "Tidak Dikenal"
        if is_penyusup and not self.last_penyusup:
            self.show_toast("PENYUSUP TERDETEKSI!")
        self.last_penyusup = is_penyusup
        
        self.stat_user.configure(text=f"User: {STATUS['active_user']}")
        dur = STATUS['work_duration']
        hrs = str(dur // 3600).zfill(2)
        mins = str((dur % 3600) // 60).zfill(2)
        secs = str(dur % 60).zfill(2)
        self.stat_dur.configure(text=f"Timer: {hrs}:{mins}:{secs}")
        
        self.after(30, self.update_video)
