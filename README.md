# 🛡️ The Ultimate Watcher V3
**An AI-Powered Personal Security & Productivity Dashboard**

The Ultimate Watcher V3 adalah sistem AI berbasis *Computer Vision* yang dibangun untuk memonitor produktivitas, mengawasi postur tubuh, mengamankan area meja kerja, dan menyediakan antarmuka interaktif ganda (Desktop & Web). 

## 🚀 Fitur Unggulan

### 💼 Productivity Tracker (Bos Virtual)
- **Deteksi Main HP**: Menggunakan *Object Detection* (COCO Dataset) untuk memergoki jika Anda diam-diam bermain *smartphone* di jam kerja! Jika ketahuan, sistem akan mengirim *Screenshot* otomatis ke Telegram Anda sebagai barang bukti.
- **Deteksi Kehadiran**: AI akan melacak apakah Anda sedang *At Desk* (Di depan layar) atau *Away* (Meninggalkan meja).
- **Status Pekerja**: Kalkulasi otomatis dari postur, tingkat kantuk, dan penggunaan HP untuk menyimpulkan apakah Anda "Fokus Bekerja" atau "Main-main".

### 📸 Manajemen Identitas Instan (FaceID)
- Daftarkan wajah Anda (dan teman Anda) langsung dari Web Dashboard maupun Desktop App hanya dengan satu klik! 
- Sistem akan otomatis mendeteksi wajah Anda, melacaknya dengan kotak hijau, dan memberikan peringatan suara/Telegram jika ada "Penyusup" di depan layar.

### 🧘 AI Trainer & Kesehatan
- **Kalkulasi Postur**: Mengingatkan Anda untuk duduk tegak jika punggung terlalu membungkuk.
- **Reps Counter**: Ingin berolahraga kecil di meja? AI akan menghitung repetisi gerakan lengan Anda secara presisi!
- **Deteksi Kantuk**: Memonitor kedipan dan lamanya mata tertutup, lalu membunyikan alarm dan peringatan Telegram jika Anda tertidur.

### 🎮 Kontrol Gestur (Hand Tracking)
- **Boss Key**: Cukup angkat jari membentuk pose "Peace/V-Sign", dan sistem akan otomatis menyembunyikan semua jendela (*Show Desktop*).
- **Screenshot Cepat**: Acungkan Jempol ke kamera, dan AI akan mendokumentasikan momen tersebut ke galeri.
- **Pendeteksi Bahasa Isyarat**: Mendeteksi gestur *"I Love You"*, *"Hello"*, dan *"OK"*.

### 🌐 Dual-Mode Architecture (Desktop & Web)
Semua fitur ini dapat dikontrol melalui:
1. **Web Dashboard**: Antarmuka *Glassmorphism* modern dengan panel *Telemetry* yang responsif. Anda bisa memantaunya dari HP (di jaringan yang sama).
2. **Desktop App**: Panel *Sidebar* ringkas bergaya *Dark Mode* menggunakan CustomTkinter, lengkap dengan indikator status *live*.

---

## 🛠️ Persyaratan Sistem
- Python 3.9 - 3.14
- Kamera Web (Webcam)
- Koneksi Internet (Untuk Bot Telegram)

## 📦 Cara Memulai

### 1. Instalasi
Jalankan perintah ini di terminal:
```bash
pip install -r requirements.txt
```

### 2. Konfigurasi
Buat sebuah file `.env` di direktori utama, lalu isikan Token Bot Telegram Anda:
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=987654321
```
Salin `.env.example` sebagai titik awal, lalu isi hanya nilai yang diperlukan.

### 3. Menjalankan Aplikasi
Eksekusi file utama, dan biarkan "Sang Pengawas" bekerja:
```bash
python main.py
```
Akses **http://localhost:5000** di *browser* Anda untuk membuka Web Dashboard, atau gunakan Desktop App yang langsung muncul di layar Anda.

### 4. WebRTC Meet (opsional)
Sebelum membuka port WebRTC, isi `WEBRTC_ADMIN_TOKEN` dan `WEBRTC_SECRET_KEY`
dengan nilai acak yang panjang. Buka halaman admin memakai
`/admin?token=<WEBRTC_ADMIN_TOKEN>`. Tanpa token, koneksi admin ditolak dan
kontrol desktop tidak aktif.

### 5. Catatan performa
- Pipeline kamera memakai buffer frame terbaru dan encoding maksimum 30 FPS
  agar latency tidak menumpuk.
- Registrasi Face ID menolak frame tanpa wajah atau dengan lebih dari satu wajah,
  memakai dua jitter saat membuat embedding, dan mengganti embedding lama saat
  nama yang sama didaftarkan ulang.
- Pastikan pencahayaan wajah cukup dan jangan mengaktifkan semua model AI berat
  sekaligus pada perangkat CPU-only.

---
*Dibangun dengan ❤️ menggunakan MediaPipe, OpenCV, Flask, dan CustomTkinter.*
