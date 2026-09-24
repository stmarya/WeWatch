# WeWatch — Audit, Operasional, dan Release Readiness

Dokumen ini merangkum hasil audit teknis terbaru, perbaikan yang sudah
diterapkan, cara menjalankan sistem, serta batasan yang harus dipenuhi sebelum
dipakai untuk deployment produksi.

## 1. Ringkasan arsitektur

WeWatch terdiri dari beberapa proses:

- **AI dashboard (`app.py`, port 5000)**  
  Menjalankan kamera, face recognition, deteksi gesture/postur/objek, galeri,
  status AI, voice listener, dan dashboard admin.
- **WebRTC signaling (`WebRTC_Meet/app.py`, port 5001)**  
  Menangani Socket.IO room, autentikasi room, presence, chat, poll,
  whiteboard, moderasi, remote assistance, dan komunikasi desktop agent.
- **Native desktop agent (`desktop_agent.py`)**  
  Berjalan di komputer client Windows dan hanya menerima command terstruktur
  yang sudah di-allowlist.
- **Redis**  
  Menyimpan shared participant state dan room state saat multi-process atau
  multi-instance deployment digunakan.
- **LiveKit dan Coturn**  
  Menyediakan fondasi SFU dan TURN untuk deployment skala besar. Client UI
  legacy belum otomatis bermigrasi ke LiveKit.

## 2. Perbaikan audit terakhir

Perbaikan terbaru sudah dipush pada commit:

`1721e56 — fix: harden signaling and audit production blockers`

Perubahan utama:

1. Default CORS signaling sekarang mencakup dashboard `localhost:5000`,
   signaling `localhost:5001`, serta alamat loopback `127.0.0.1`.
2. URL signaling dashboard mengikuti protokol halaman yang sedang digunakan.
3. Live caption sekarang membawa nama pengirim dan tidak lagi kehilangan
   identitas pembicara.
4. Load test menggunakan `join_token` yang benar ketika token enforcement
   aktif.
5. Startup Face ID lebih aman ketika foto legacy tidak berisi wajah.
6. Payload event `join` yang bukan object tidak lagi langsung menyebabkan
   error akses `.get()`.
7. Dokumentasi konfigurasi origin, token, dan smoke test diperjelas.

## 3. Konfigurasi minimum

Salin konfigurasi awal:

```bash
cp .env.example .env
```

Nilai minimum untuk dashboard:

```env
WEBWATCH_SESSION_SECRET=<random-secret-minimal-32-karakter>
```

Nilai minimum untuk WebRTC:

```env
WEBRTC_ADMIN_TOKEN=<random-admin-token>
WEBRTC_SECRET_KEY=<random-secret-minimal-32-karakter>
WEBRTC_ALLOWED_ORIGINS=http://localhost:5000,http://localhost:5001
WEBRTC_ROOM_NAME=gmeet_room
WEBRTC_REQUIRE_JOIN_TOKEN=false
```

Untuk desktop agent:

```env
DESKTOP_AGENT_TOKEN=<random-agent-token>
DESKTOP_AGENT_IDENTITY=workstation-01
DESKTOP_AGENT_TARGET_IDENTITY=<identity-client>
DESKTOP_AGENT_ALLOW_DANGEROUS=false
DESKTOP_AGENT_ALLOWED_PROCESSES=
```

Jangan commit file `.env`, token, credential TURN, atau secret LiveKit.

## 4. Menjalankan development

Install dependency:

```bash
python -m pip install -r requirements.txt
```

Jalankan dashboard:

```bash
python main.py
```

Jalankan signaling server pada terminal terpisah:

```bash
python WebRTC_Meet/app.py
```

Endpoint penting:

- Dashboard: `http://localhost:5000/`
- Client meeting: `http://localhost:5001/`
- Health check signaling: `http://localhost:5001/healthz`
- Readiness check signaling: `http://localhost:5001/readyz`

Dashboard admin memakai session login dan CSRF protection. Jangan memakai
query-string token sebagai mekanisme login dashboard baru.

## 5. Desktop agent

Desktop agent wajib dijalankan di komputer yang memang ingin dikontrol, bukan
di signaling server. Jalankan setelah konfigurasi environment tersedia:

```bash
python desktop_agent.py
```

Command yang tersedia dibatasi ke kategori berikut:

- Mouse move, click, dan scroll
- Keyboard text, key, dan hotkey
- Show desktop, Task Manager, Explorer, close window
- Volume control
- Open URL `http://` atau `https://`
- Screenshot
- Telemetry Windows
- Clipboard, lock workstation, dan process control hanya jika policy
  dangerous actions diaktifkan

`DESKTOP_AGENT_ALLOW_DANGEROUS=false` harus tetap menjadi default. Agent tidak
menjalankan arbitrary shell command.

## 6. Validasi sebelum release

Jalankan semua pemeriksaan lokal berikut dari root repo:

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
python -m compileall -q .
python -m py_compile desktop_agent.py tools/load_test_signaling.py
```

Periksa sintaks JavaScript dengan mengekstrak script template dan menjalankan:

```bash
node --check <extracted-template-script.js>
```

Smoke test signaling tanpa token enforcement:

```bash
python tools/load_test_signaling.py \
  --url http://localhost:5001 \
  --count 25 \
  --workers 25
```

Jika token enforcement aktif, berikan token client berumur pendek:

```bash
python tools/load_test_signaling.py \
  --url http://localhost:5001 \
  --count 25 \
  --workers 25 \
  --join-token "<CLIENT_JOIN_TOKEN>"
```

## 7. Deployment skala besar

Jalankan stack pendukung:

```bash
docker compose -f docker-compose.scale.yml up -d
```

Sebelum production:

- Ganti seluruh placeholder `change-me`.
- Gunakan TLS untuk dashboard, signaling, LiveKit, dan TURN.
- Atur firewall serta rate limit.
- Gunakan Redis yang persistent dan dipantau.
- Gunakan secret LiveKit dan TURN yang berbeda dari token aplikasi.
- Sediakan observability untuk CPU, memory, connection count, signaling
  latency, packet loss, reconnect, dan TURN relay usage.

### Release gates yang disarankan

- Minimal 600 concurrent signaling joins.
- Join success rate minimal 99%.
- p95 signaling latency di bawah 200 ms.
- First media di bawah 5 detik.
- Reconnect success minimal 98%.
- Tidak ada peningkatan error rate saat Redis failover.
- Tidak ada kebocoran secret pada URL, log, HTML, atau browser storage.

## 8. Batasan dan blocker yang masih terbuka

Audit terbaru memperbaiki blocker konfigurasi dan alur signaling, tetapi belum
menutup semua pekerjaan production-scale:

1. **UI meeting masih memakai raw peer-to-peer WebRTC.**  
   Infrastruktur LiveKit sudah disiapkan, tetapi halaman client/admin belum
   sepenuhnya menggunakan LiveKit SDK. Satu admin yang membuat peer connection
   ke ratusan client tidak dapat dianggap setara dengan arsitektur SFU.
2. **Belum ada load test media 500+ peserta.**  
   Smoke test signaling hanya menguji koneksi dan join, bukan video, audio,
   simulcast, subscription policy, atau TURN relay.
3. **Native agent belum diuji end-to-end pada Windows hardware nyata.**  
   Pengujian harus mencakup permission desktop, pyautogui, screenshot, audio,
   reconnect, dan policy dangerous actions.
4. **Voice AI masih bergantung pada microphone dan layanan speech/TTS.**  
   Fallback tersedia, tetapi kualitas dan latency belum dapat dijamin tanpa
   pengujian perangkat, jaringan, dan model suara yang ditentukan.
5. **Face recognition memerlukan kalibrasi operasional.**  
   Pencahayaan, sudut kamera, kualitas enrollment, threshold, dan jumlah wajah
   harus diuji dengan dataset internal sebelum dijadikan kontrol akses.

Karena itu, status yang benar saat ini adalah **release candidate untuk
development dan pilot terbatas**, bukan jaminan production-ready 500+ peserta.

## 9. Prosedur incident singkat

Jika signaling gagal:

1. Periksa `/healthz` dan `/readyz`.
2. Periksa `WEBRTC_SECRET_KEY`, `WEBRTC_ADMIN_TOKEN`, dan
   `WEBRTC_ALLOWED_ORIGINS`.
3. Pastikan port 5000 dan 5001 dapat dijangkau dari browser.
4. Periksa Redis bila aplikasi memakai lebih dari satu worker.
5. Periksa browser console untuk error Socket.IO/CORS.

Jika media tersendat:

1. Periksa apakah room masih memakai raw P2P.
2. Kurangi jumlah video aktif dan resolusi kamera.
3. Periksa CPU, memory, packet loss, dan TURN usage.
4. Jangan menaikkan batas peserta sebelum SFU client dan load test media
   selesai.

Jika Face ID lambat:

1. Matikan model AI berat yang tidak diperlukan.
2. Gunakan pencahayaan frontal dan satu wajah saat enrollment.
3. Periksa `faces/` dan log startup.
4. Uji ulang threshold dengan data internal, bukan hanya satu foto.