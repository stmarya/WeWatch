# Setup pilot aman — perubahan 15 Oktober 2026

Status: pilot terbatas, bukan jaminan production-ready. Terapkan branch audit
melalui PR; jangan membuka service QA, kamera, atau desktop agent ke internet.

## 1. Instalasi dan konfigurasi

Gunakan Python 3.11–3.13 untuk signaling/tests (sesuai CI). Dependency camera,
dlib, MediaPipe, microphone, dan desktop perlu diuji tersendiri per OS.

```bash
python -m pip install -r requirements-signaling.txt
cp .env.example .env
```

Untuk aplikasi AI/desktop gunakan `requirements.txt`. Windows-only dependencies
sudah memakai platform markers. Compiler dlib dan desktop session tetap perlu.
SpeechRecognition microphone memerlukan PyAudio jika voice cloud diaktifkan.

Isi `WEBRTC_ADMIN_TOKEN`, `WEBRTC_SECRET_KEY`, dan `WEBWATCH_SESSION_SECRET`
dengan secret berbeda, minimal 32 karakter, dari password manager. Jangan
menyalin credential contoh atau fixture tes. `WEBRTC_REQUIRE_JOIN_TOKEN=true`
adalah default baru. Aplikasi bind `127.0.0.1` secara default.

Signaling sekarang membaca `.env` dari root repo. Dashboard menjalankan kamera
lokal saat proses dimulai; jalankan hanya pada perangkat dan orang yang sudah
menyetujui pemrosesan kamera. Preview browser client berbeda: opt-in per klik.

Untuk pilot single-process tanpa Redis, kosongkan `REDIS_URL`. Untuk beberapa
worker/instance, Redis wajib sehat dan `WEBRTC_REQUIRE_SHARED_STATE=true`.
Atur allowed origins sesuai origin nyata, tanpa wildcard. Jangan mengandalkan
limiter in-memory sebagai batas global multi-worker.

## 2. Join client dan LiveKit

Admin mengeluarkan token melalui API server yang terautentikasi:

```text
POST /api/room-token
X-Admin-Token: <admin secret>
Content-Type: application/json
{"identity":"participant-01","role":"client","ttl":300}
```

Tempel `join_token` pada input token di `/client` atau `/livekit`. Nama tampilan
boleh berbeda dari identity token. Jangan memasukkan bearer token dalam URL,
chat publik, localStorage, log, atau link bersama. Import query-string lama
hanya kompatibilitas sementara: UI segera menghapusnya dari address bar,
namun request awal masih bisa masuk ke access log proxy. Gunakan input token.

Admin ticket dashboard mengikuti `WEBRTC_ROOM_NAME`. Token media tidak boleh
berumur lebih panjang dari sisa umur token undangan. Setelah ticket kedaluwarsa,
reconnect memerlukan ticket baru. Token undangan bukan mekanisme revokasi sesi
media yang sudah berjalan; moderation SFU perlu integrasi server tersendiri.

## 3. Remote assistance

Client wajib bergabung dan mencentang persetujuan khusus. Konfirmasi menjelaskan
hak mouse/keyboard, screenshot, dan perintah host. Persetujuan otomatis habis
setelah 10 menit, dapat dicabut, dan tidak dapat diberikan oleh host.

Pada komputer Windows target:

```env
DESKTOP_AGENT_IDENTITY=workstation-01
DESKTOP_AGENT_TARGET_IDENTITY=participant-01
DESKTOP_AGENT_ALLOW_REMOTE_CONTROL=true
DESKTOP_AGENT_ALLOW_DANGEROUS=false
```

Keluarkan **ticket perangkat terikat identity** melalui API admin:

```text
{"identity":"workstation-01","role":"agent","target_identity":"participant-01","ttl":300}
```

Isi hasil `join_token` sebagai `DESKTOP_AGENT_JOIN_TOKEN` lalu jalankan
`python desktop_agent.py`. Jangan berikan admin secret ke workstation client.
Static agent token ditolak secara default. `WEBRTC_ALLOW_STATIC_AGENT_TOKEN=true`
hanya compatibility development dan tidak boleh menjadi kebijakan produksi.

Jika policy lokal tetap `DESKTOP_AGENT_ALLOW_REMOTE_CONTROL=false`, semua command
native ditolak walaupun host punya hak admin. `ALLOW_DANGEROUS=false` memblokir
clipboard injection, lock workstation, dan process kill; **bukan sandbox input**.
Mouse/keyboard yang diizinkan adalah akses desktop luas dan dapat mengoperasikan
aplikasi/shell. Jalankan dengan privilege OS minimum dan supervision pengguna.

Command pending maksimal 30 detik. Revocation menghentikan pengiriman berikutnya
serta forwarding hasil/screenshot, tetapi tidak membatalkan operasi OS yang
sudah diterima/dijalankan. Stop agent secara lokal untuk emergency stop.

## 4. Opt-in privasi

Default semua flag berikut `false`:

| Flag | Efek saat diaktifkan |
| --- | --- |
| `ALERT_CAPTURE_ENABLED` | Menyimpan foto alert otomatis ke galeri lokal |
| `TELEGRAM_UPLOAD_ENABLED` | Mengirim foto alert ke Telegram; perlu flag capture juga |
| `MOOD_LOG_ENABLED` | Menyimpan label ekspresi di SQLite |
| `VOICE_CLOUD_ENABLED` | Google speech recognition dan Edge TTS; data audio/teks keluar perangkat |
| `RPPG_EXPERIMENTAL_ENABLED` | Mengizinkan eksperimen estimator pulse; bukan alat medis |

Manual snapshot dan enrollment tetap menyimpan gambar atas tindakan admin.
Gesture snapshot hanya aktif bila fitur hands diaktifkan. Belum ada deletion/
retention UI; tetapkan jadwal penghapusan galeri, enrollments, mood/attendance
DB dan backup, serta akses filesystem minimum sebelum pilot dengan data nyata.

Face ID, gerakan, postur, ekspresi, gaze, dan deteksi ponsel hanya sinyal heuristik.
Jangan menjadikannya otorisasi, diagnosis medis, penilaian emosi/kinerja, atau
bukti pelanggaran otomatis.

## 5. Validasi

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
python -m compileall -q .
python tools/check_template_js.py
python tools/audit_ui_inventory.py
git diff --check
```

Browser QA menggunakan kamera tiruan dan fixture credential **khusus loopback**:

1. Sediakan Node, Playwright, dan Chromium lokal (bukan browser user).
2. Buat folder privat: `export WEWATCH_QA_DIR="$(mktemp -d)"` (mode 0700).
3. Terminal pertama: `python tools/run_browser_qa_server.py`. Terminal kedua: export path `WEWATCH_QA_DIR` yang sama, lalu `CHROMIUM_PATH=/path/to/chromium node tools/browser_qa.cjs`.
4. Hasil/screenshot dan token fixture berada di folder privat tersebut. Hapus setelah QA.
5. Stop server QA setelah selesai. Jangan deploy harness QA.

## 6. Gate produksi (NO-GO jika belum terpenuhi)

- TLS, secure cookies, secret persistence, reverse proxy limits, dan port firewall.
- Redis failure/recovery dan atomic identity/capacity admission lintas worker.
- End-to-end Windows desktop agent: pairing, consent, replay, stop/reconnect.
- Kamera/mikrofon nyata dan kalibrasi threshold dengan data berizin.
- Model integrity/provenance, model latency/CPU, spoof/bias evaluation.
- Self-host/version-pin LiveKit SDK dan evaluasi external font/CDN dependencies.
- Migrasi P2P ke SFU, TURN credentials/TLS, moderation/permission enforcement SFU.
- Media load test (bukan sekadar signaling), retention/deletion dan privacy policy.
- Keyboard/modal focus, contrast, responsive in-call/remote panels dan browser matrix.
