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
- Python 3.12 atau lebih baru untuk instalasi penuh (`requirements.lock`)
- Kamera Web (Webcam)
- Koneksi Internet (Untuk Bot Telegram)

## 📦 Cara Memulai

### 1. Instalasi
Jalankan perintah ini di terminal:
```bash
python -m pip install --require-hashes -r requirements.lock
```

### 2. Konfigurasi
Buat sebuah file `.env` di direktori utama, lalu isikan Token Bot Telegram Anda:
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=987654321
```
Salin `.env.example` sebagai titik awal. Isi `WEBWATCH_SESSION_SECRET` dengan
secret acak minimal 32 karakter; gunakan secret yang berbeda dari
`WEBRTC_SECRET_KEY` dan `WEBRTC_ADMIN_TOKEN`. Mode development hanya mengikat
dashboard dan signaling ke loopback. Jangan membuka server development ke
jaringan.
Dashboard utama meminta login admin dan tidak menaruh admin secret di HTML.
Dokumentasi audit, operasional, dan release readiness tersedia di
[`docs/AUDIT_AND_OPERATIONS.md`](docs/AUDIT_AND_OPERATIONS.md).
Sebelum penggunaan kamera atau pemantauan orang lain, baca
[`docs/PRIVACY_AND_CONSENT.md`](docs/PRIVACY_AND_CONSENT.md). Mood logging,
penyimpanan salinan foto Telegram, deteksi kantuk, dan screenshot agent kini
opt-in; tetapkan persetujuan dan retensi terlebih dahulu.
Setiap push dan pull request ke `main` juga menjalankan workflow CI untuk unit
test, compile check, validasi JavaScript template, dan whitespace check.

### 3. Menjalankan Aplikasi
Eksekusi file utama, dan biarkan "Sang Pengawas" bekerja:
```bash
python main.py
```
Akses **http://localhost:5000** di *browser* Anda untuk membuka Web Dashboard, atau gunakan Desktop App yang langsung muncul di layar Anda.

### 4. WebRTC Meet (opsional)
WebRTC join-token enforcement aktif secara default. Isi `WEBRTC_ADMIN_TOKEN`
dan `WEBRTC_SECRET_KEY` dengan secret acak minimal 32 karakter. Untuk
development lokal, set `WEBRTC_ALLOW_UNSAFE_WERKZEUG=true` secara eksplisit
hanya saat host tetap loopback. Untuk deployment jaringan, gunakan server
produksi yang sesuai di belakang TLS/reverse proxy; jangan aktifkan Werkzeug
unsafe.
Buka dashboard admin di
`http://localhost:5000/` dan halaman client/signaling di
`http://localhost:5001/`. Dashboard akan meminta admin token; tanpa token,
koneksi admin ditolak dan kontrol desktop tidak aktif. Jika client berada di
host lain, atur `WEBRTC_ALLOWED_ORIGINS` sebagai daftar origin yang dipisahkan
koma. Default development mencakup port 5000 dan 5001 pada `localhost` serta
`127.0.0.1`.

### 5. Catatan performa
- Pipeline kamera memakai buffer frame terbaru dan encoding maksimum 30 FPS
  agar latency tidak menumpuk.
- Registrasi Face ID menolak frame tanpa wajah atau dengan lebih dari satu wajah,
  memakai dua jitter saat membuat embedding, dan mengganti embedding lama saat
  nama yang sama didaftarkan ulang.
- Pastikan pencahayaan wajah cukup dan jangan mengaktifkan semua model AI berat
  sekaligus pada perangkat CPU-only.

### 6. Scale profile dan reliability
Untuk meeting besar, gunakan `docker-compose.scale.yml` dengan Redis, LiveKit,
dan Coturn. State participant, lock meeting, poll, dan whiteboard akan memakai
shared room state saat `REDIS_URL` aktif. Jalankan `tools/load_test_signaling.py`
sebelum membuka room untuk pengguna dan tetapkan release gate minimal 600
koneksi berhasil.

Jika `WEBRTC_REQUIRE_JOIN_TOKEN=true`, sertakan token client berumur pendek
ketika menjalankan smoke test:

```bash
python tools/load_test_signaling.py --count 25 --join-token "<CLIENT_JOIN_TOKEN>"
```

Untuk menguji 500 signaling participant dengan token unik per identity:

```bash
WEBRTC_ADMIN_TOKEN="<ADMIN_TOKEN>" \
python tools/load_test_signaling.py \
  --count 500 --workers 100 \
  --admin-token "$WEBRTC_ADMIN_TOKEN" \
  --min-success-rate 0.99 \
  --json-out /tmp/wewatch-signaling-500.json
```

Smoke test ini belum menggantikan media load test LiveKit untuk audio/video.

### 7. Native Desktop Agent (opsional)
Untuk remote mouse, keyboard, screenshot, volume, dan workflow desktop,
jalankan `desktop_agent.py` pada komputer client. Agent membatasi hotkey dan
tidak menjalankan arbitrary shell command. Koneksi non-loopback wajib memakai
HTTPS/WSS. Screenshot mati secara default; aktifkan
`DESKTOP_AGENT_ALLOW_SCREENSHOTS=true` hanya dengan persetujuan pemilik
workstation. Isi `DESKTOP_AGENT_TOKEN` dengan secret acak minimal 32 karakter,
`DESKTOP_AGENT_IDENTITY`, dan
`DESKTOP_AGENT_TARGET_IDENTITY`, lalu jalankan:

```bash
python desktop_agent.py
```

Biarkan `DESKTOP_AGENT_ALLOW_DANGEROUS=false` kecuali policy organisasi sudah
menyetujui clipboard injection, workstation lock, atau process control.

---
*Dibangun dengan ❤️ menggunakan MediaPipe, OpenCV, Flask, dan CustomTkinter.*
