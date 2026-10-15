# WeWatch Platform — Tahap 2: onboarding browser & consent

Status: core pilot browser diimplementasikan, belum di-merge/deploy. Dibangun di atas tahap 1 / PR #4, commit a9a508090acadc824dde9d877acb22a72c14d0ab. **NO-GO produksi publik**: gate tahap 1 tetap berlaku.

## Apa yang tersedia — dan apa yang tidak

- Onboarding per workspace, pairing **sesi browser**, pemeriksaan dukungan browser tanpa membuka media, preview kamera/mikrofon lokal dengan izin terpisah, countdown dan tombol STOP, serta daftar/cabut pairing.
- Tidak ada kredensial desktop agent, device hardware attestation, enrollment Windows, akses mouse/keyboard, perintah host, screenshot, screen sharing, AI, rekaman, transkripsi, upload atau meeting yang diaktifkan.
- Readiness adalah laporan browser yang tidak dipercaya untuk otorisasi; label sesi ditulis pengguna dan bukan bukti nama/identitas hardware.
- Pairing browser bukan persetujuan media. Persetujuan media lokal bukan izin remote atau izin memproses biometrik.

## Cara memakai

Jalankan pilot tahap 1 sesuai [panduan setup](PLATFORM_PHASE_1.md). Tidak ada dependency runtime atau secret baru. Gunakan HTTPS atau loopback (`http://127.0.0.1:5002`) yang mendukung media secure context.

1. Register → verifikasi → login → pilih workspace.
2. Buka **Siapkan browser & izin** pada halaman workspace. Owner/Admin/Host/Member boleh pairing sendiri; Viewer hanya dapat melihat halaman diagnostik, tanpa pairing/preview.
3. Isi nama sesi browser → **Buat token pairing**. Token 256-bit, sekali pakai, TTL 5 menit, digest SHA-256 di DB. Permintaan baru membatalkan token lama pada sesi/workspace ini. Token dapat dibatalkan sebelum dipakai.
4. **Tinjau & konfirmasi** membuka `/device-pairing#token=...`. Token dihapus dari URL oleh JS; GET tidak menyetujui pairing. Pilih **Periksa permintaan**, periksa nama sesi/workspace, lalu **Saya mengenali sesi ini · Setujui pairing**. Akun harus sama; boleh meninjau dari sesi akun lain tetapi binding selalu ke **sesi peminta**, bukan sesi peninjau. Jangan menyetujui token dari pihak lain.
5. Kembali ke browser peminta dan muat ulang status. Pairing tidak membuka media. **Periksa tanpa membuka media** hanya memeriksa secure context/API media.
6. Pilih **Izinkan & preview kamera** atau **Izinkan & uji mikrofon** sesuai kebutuhan. Teks menjelaskan ruang lingkup sebelum tombol; masing-masing meminta grant server dan izin browser/OS secara terpisah. Mikrofon hanya membuka track audio lokal, tidak diputar atau disimpan; tidak ada meter medis/fokus/kinerja.
7. Pilih stop per kapabilitas atau **STOP** untuk semua. Mulai kembali hanya melalui tindakan manual. Untuk melepas sesi, pilih **Cabut pairing**.

Bila permission ditolak, periksa izin situs/OS lalu coba manual; aplikasi tidak mencoba melewati penolakan. Tanpa JavaScript, preview/pairing tidak berjalan dan tidak ada fallback yang membuka media. Jika link pairing dibuka sebelum login, login terlebih dahulu lalu buka ulang link tersebut; token tidak disimpan di localStorage/sessionStorage.

## Threat model & invariant

| Area | Aturan |
| --- | --- |
| Workspace | Semua operasi mengecek keanggotaan akun aktif/terverifikasi; penulisan mengecek lagi di transaksi |
| Identitas browser | Binding `workspace_id + user_id + initiating account_session_id`; UUID/label bukan autentikator |
| Token | Sekali pakai, 5 menit, digest saja di DB; raw token hanya response/form/fragment, tidak log/audit atau query string |
| Sesi | Pairing tidak melampaui sesi login: absolute 8 jam / idle 30 menit; tidak ada device bearer jangka panjang |
| Preview | Hanya `camera_preview` / `microphone_preview`, policy `local-preview-v1`, `acknowledged` harus boolean true; TTL maksimal 10 menit dan tidak melampaui sesi |
| Role | Viewer ditolak; Owner/Admin tidak boleh grant media milik orang lain atau sesi lain, tetapi boleh mencabut pairing workspace |
| Role berubah | Semua perubahan role (termasuk transfer ownership), leave/remove, disable akun, revoke/logout/reset men-tombstone pairing dan consent. Kembalinya role/keanggotaan tidak menghidupkan kembali izin lama |
| Readiness | Hanya boolean secure context/API serta enum kamera/mikrofon. Menolak raw frame, media, label, device ID, UA, arbitrary fields; tidak memberikan izin apa pun |
| Remote & AI | Semua capability AI/remote ditolak server; tidak ada endpoint bridge ke layanan lama |

Approval token dan grant/revoke diserialisasi dengan `BEGIN IMMEDIATE`. Unique index menjaga satu browser aktif per sesi/workspace. Pilot membatasi 10 sesi browser aktif per akun/workspace. Rate limit tahap 1 berlaku untuk semua mutasi; produksi masih memerlukan limit terdistribusi/retention.

## Lifecycle preview dan batas jaminan

`getUserMedia` hanya dipanggil setelah klik kapabilitas dan respons grant. Kamera dipasang pada video muted lokal; audio hanya menjadi track, tidak dikirim ke AudioContext/recorder/provider. Tidak ada `getDisplayMedia`, MediaRecorder, WebRTC peer connection, atau API remote pada modul baru.

- STOP menghentikan `MediaStreamTrack` lokal dahulu, baru meminta pencabutan server. Kegagalan pencabutan ditampilkan dengan jujur; grant server tetap memiliki batas TTL.
- Izin ditolak, media hilang/track ended, acquisition timeout 60 detik, offline, pagehide, tab hidden, grant expiry, dan kegagalan pemeriksaan status menghentikan preview. Late permission result setelah STOP tidak dipasang dan track-nya langsung dihentikan.
- Pemeriksaan server setiap 4 detik, request timeout 3 detik: pencabutan dari sesi/admin lain terdeteksi pada siklus berikutnya (nominal hingga sekitar 7 detik pada tab terlihat). **Bukan jaminan hard real-time**; event loop/background suspension dan perilaku browser/OS dapat memengaruhi waktu eksekusi.
- Refresh/back/online kembali tidak memulai media otomatis. Halaman baru juga meminta revoke grant lama; tindakan manual diperlukan untuk memulai lagi.
- Ledger server mengotorisasi **niat preview aplikasi**, bukan memaksakan OS permission. Server tidak bisa mencegah pengguna menjalankan JavaScript sendiri atau memegang kamera pada aplikasi lain. Karena tidak ada media yang diterima server, jangan memakai ledger/readiness ini sebagai bukti kepatuhan endpoint atau sebagai izin remote.

Permissions-Policy kamera/mikrofon tetap deny pada halaman akun/dasbor/API; hanya halaman onboarding role non-Viewer mengizinkan `(self)`. CSP mengizinkan media self/blob untuk preview, tanpa inline script atau third-party asset. Cookie/CSRF/origin protections tahap 1 tetap berlaku. Jangan log body request atau Cookie, dan jangan kirim token pairing melalui analytics.

## Migrasi dan operasi

SQLite migrasi v2 **aditif** mempertahankan akun/workspace/sesi v1 dan menambahkan `browser_devices`, `device_pairings`, `preview_consents`, `browser_readiness` serta trigger pencabutan. Startup idempoten; aplikasi v1 menolak skema yang lebih baru. Backup konsisten DB/WAL sebelum upgrade. Rollback kode ke v1 membutuhkan restore backup yang sesuai; jangan menghapus tabel/migration marker sembarangan.

Daftar UI menampilkan maksimal 50 pairing terbaru; ini bukan konsol perangkat enterprise atau audit/retention lengkap. Session expiry efektif diperiksa saat akses, walaupun baris historis masih ada; expiry tidak berarti penghapusan data. Retention, deletion/export dan audit archive tetap tahap 4.

## Endpoint tambahan

- GET `/workspaces/<id>/onboarding`, GET `/api/workspaces/<id>/onboarding`.
- POST `/workspaces/<id>/pairing`, POST `/workspaces/<id>/pairing/<pairing_id>/cancel`.
- GET `/device-pairing`; POST `/device-pairing/inspect`, `/device-pairing/approve`.
- POST `/workspaces/<id>/devices/<device_id>/readiness`.
- POST `/workspaces/<id>/devices/<device_id>/consents`, `/consents/revoke`, `/revoke`.

Semua POST perlu CSRF, JSON melalui `X-CSRF-Token`; revoke memakai form/`sendBeacon` menyertakan field CSRF. Status hanya mengembalikan sesi browser saat ini; tidak memberi token pairing, password hash, atau identitas hardware. Owner/Admin melihat daftar perangkat via halaman dengan scope workspace, bukan akses media.

## Validasi dan cara mengulang

```bash
python -m pip install -r requirements-signaling.txt -r requirements-platform.txt
PYTHONPATH=. python -m unittest discover -s tests -v
node --check platform_static/onboarding.js
node --test tests/test_preview_controller.cjs
python -m compileall -q platform_app.py platform_core tests
```

Hasil lokal: **131 tes Python** (39 baru tahap 2), **16 tes controller JS**, **24 assertion browser tahap 2** dan **19 regression browser tahap 1**. Bandit runtime platform: 0 temuan; pip-audit requirements platform: 0 advisory yang diketahui. Tidak menggantikan review manual/pentest.

Browser QA memakai Playwright 1.64.1 + Chromium dengan **fake media**. Server fixture hanya loopback dan secret diketahui; jangan deploy. Gunakan dua terminal dengan direktori kosong privat yang sama:

```bash
# Terminal 1
export WEWATCH_QA_DIR="$(mktemp -d)"
python tools/run_platform_qa_server.py
# Terminal 2: set WEWATCH_QA_DIR persis sama, bukan mktemp baru.
npm install --prefix /tmp/wewatch-qa-deps playwright@1.64.1
NODE_PATH=/tmp/wewatch-qa-deps/node_modules CHROMIUM_PATH=/path/to/chromium \
  node tools/onboarding_browser_qa.cjs
# Opsional regresi tahap 1 memakai email fixture berbeda:
NODE_PATH=/tmp/wewatch-qa-deps/node_modules CHROMIUM_PATH=/path/to/chromium \
  node tools/platform_browser_qa.cjs
```

Buat direktori/DB kosong untuk run ulang. Snapshot/DB/mail/CSRF fixture jangan di-commit; hapus setelah pengujian. Pagehide browser QA memakai sinyal lifecycle DOM deterministik, bukan validasi penjadwalan background OS. Izin ditolak disimulasikan. Bukti terstruktur: [PLATFORM_PHASE_2_VALIDATION.json](PLATFORM_PHASE_2_VALIDATION.json).

## Gate menuju tahap 3 dan produksi

- Browser/perangkat nyata, permission UX/indikator OS, disconnect, tab suspension/BFCache dan iOS/Safari/Firefox belum diuji; fake media bukan bukti kamera/mikrofon nyata.
- Device credentials persisten/hardware binding, bootstrap/rotation Windows agent, target/workspace/room bindings dan command authorization belum dibuat. Pairing browser tidak boleh diteruskan sebagai token agent.
- Remote consent yang dapat dieksekusi memerlukan target, penerima akses, capability allowlist, TTL pendek, local approval pada endpoint, revoke pada kedua sisi, indikator sesi dan emergency stop. Tahap 2 menolak seluruh remote grants sampai integrasi aman itu ada.
- AI/model readiness dan benchmark kualitas belum terhubung. Jangan menganggap diagnostics browser sebagai hasil benchmark atau label identitas/fokus/kesehatan.
- Gate SMTP/SSO-MFA/managed DB/production WSGI/TLS/backup/retention tahap 1 tetap terbuka. Tidak ada merge/deployment atau klaim platform lengkap.
