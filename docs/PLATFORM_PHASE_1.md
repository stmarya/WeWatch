# WeWatch Platform — Tahap 1

> Catatan versi: dokumen ini mencatat baseline tahap 1. Tahap 2 menambahkan migrasi v2 dan preview browser lokal berizin, tanpa menghubungkan layanan lama. Lihat [PLATFORM_PHASE_2.md](PLATFORM_PHASE_2.md).

Status: fondasi pilot lokal diimplementasikan; review/merge dan production approval belum dilakukan. Berbasis audit PR #3 (commit a6c404987e24037bfabf04d371eca0aa3f84704c).

## Batas implementasi

Control plane baru `platform_app.py` berjalan terpisah pada loopback port 5002. Tidak mengimpor atau membuka kamera, model AI, mikrofon, desktop agent, maupun server meeting lama. Akun dan role baru **tidak** memberi izin ke layanan lama. Jangan reverse-proxy endpoint lama sebagai bagian dari platform sebelum binding workspace/perangkat dan otorisasi tahap 2–3 selesai.

## Menjalankan pilot lokal

Python 3.11–3.13, disarankan virtual environment baru:

```bash
python -m venv .venv-platform
source .venv-platform/bin/activate
python -m pip install -r requirements-platform.txt
# Salin .env.example ke .env jika belum ada; jangan timpa konfigurasi lama.
# Generate secret privat yang BERBEDA dari secret/token layanan lain:
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Masukkan hasil generator ke `PLATFORM_SESSION_SECRET` melalui editor/env privat, bukan source control. Konfigurasi pengembangan:

```dotenv
PLATFORM_ENV=development
PLATFORM_PUBLIC_URL=http://127.0.0.1:5002
PLATFORM_PORT=5002
PLATFORM_MAIL_TRANSPORT=file
PLATFORM_MAIL_FROM=no-reply@wewatch.example
```

```bash
flask --app platform_app:create_app check-platform
python platform_app.py
```

Buka `http://127.0.0.1:5002/register`. Mode `file` menulis email ke `instance/platform/outbox/*.eml` (direktori 0700, file 0600); hanya diizinkan untuk development dengan origin loopback. Baca email secara lokal dan buka tautan verifikasi; jangan publikasikan mailbox ini. Tidak ada email sungguhan yang dikirim. `disabled` adalah default aman: register/reset/undangan menolak dengan 503 sampai pengiriman dikonfigurasi.

Database default `instance/platform/platform.sqlite3` dibuat dengan migrasi idempoten v1, WAL dan foreign keys; direktori privat 0700, DB 0600. Path DB/mail kosong memakai default. Jangan gunakan direktori static/public/shared. Jangan menyalin SQLite yang sedang aktif sebagai prosedur backup; gunakan SQLite backup API atau hentikan proses sebelum backup konsisten. Lindungi backup sama seperti DB asli. Permission POSIX bukan pengganti ACL Windows; Windows belum divalidasi.

## Alur dan fitur

- Daftar (display name, email, passphrase 12–128 karakter), verifikasi email, kirim ulang, login, pemulihan password.
- Email verifikasi berlaku 24 jam, reset 15 menit, undangan 72 jam; token sekali pakai dan digest SHA-256 di DB. Pengiriman ulang membatalkan token sebelumnya.
- Link bearer memakai fragment `#token=...`; JS self-hosted memindahkan ke input dan menghapus fragment. GET tidak mengonsumsi token. Tanpa JS, tempel token secara manual dan konfirmasi POST.
- Session server-side dapat dicabut, maksimum 8 jam dan idle 30 menit. Logout sesi ini / semua sesi, reset mencabut semua sesi. Cookie ditandatangani memuat bearer sesi, sementara DB menyimpan digest; jangan log header Cookie.
- Buat/pilih workspace, ganti nama, undang/cabut undangan, kelola role/hapus anggota, keluar, transfer ownership dengan password ulang. Maksimum pilot 20 workspace yang dibuat per akun dan 100 undangan aktif/workspace.
- Audit akun/workspace menyimpan event dan identitas aktor, bukan password, token, email body, audio atau biometrik. UI Owner/Admin menampilkan 30 event workspace terbaru; ini bukan audit archive/compliance system.

## RBAC

| Role | Lihat workspace | Settings / audit | Kelola anggota | Transfer Owner |
| --- | --- | --- | --- | --- |
| Owner | Ya | Ya | Semua non-Owner; dapat menunjuk Admin | Ya, reautentikasi |
| Admin | Ya | Ya | Host/Member/Viewer; tidak dapat mengubah Admin/Owner | Tidak |
| Host / Member / Viewer | Ya | Tidak | Tidak | Tidak |

Role Host belum memberi hak hosting meeting/kontrol perangkat. Selalu tepat satu Owner lewat transaksi dan unique partial index; Owner harus transfer sebelum keluar. Transfer menjadikan Owner sebelumnya Admin. Undangan mengikat email penerima, memeriksa ulang izin pengundang saat diterima, dan tidak bisa dipakai ulang. Izin diperiksa ulang dalam transaksi penulisan; UUID bukan batas keamanan. Akses workspace asing memberikan 404; role tidak cukup pada workspace sendiri memberikan 403. Tidak ada global super-admin tersembunyi atau akun bootstrap dengan password default.

## Endpoint inventory

- Akun: `/register`, `/login`, `/verify-email`, `/verification/resend`, `/password/forgot`, `/password/reset`, POST `/logout`, POST `/account/logout-all`.
- Workspace: `/app`, POST `/workspaces`, GET `/workspaces/<id>`, POST suffix `/settings`, `/invitations`, `/invitations/<invitation_id>/revoke`, `/members/<user_id>/role`, `/members/<user_id>/remove`, `/leave`, `/ownership`.
- Undangan: `/invitations/accept` (GET/POST).
- JSON reads: `/api/me`, `/api/session` (CSRF), `/api/workspaces/<id>`, `/api/workspaces/<id>/audit`.
- Health: `/healthz`, `/readyz`; readiness menunjukkan konfigurasi mail, **bukan** bukti deliverability SMTP atau kesiapan produksi.

Semua request mutasi memerlukan token CSRF, termasuk login/register. JSON menggunakan `X-CSRF-Token`. Origin lintas situs ditolak. `Origin:null` hanya diterima bila `Sec-Fetch-Site:same-origin` **dan** CSRF valid, untuk kompatibilitas form Chromium dengan no-referrer. Trusted Host, CSP tanpa inline JS, HttpOnly/SameSite cookie, no-store, no-referrer, dan Permissions-Policy camera/microphone denied diterapkan. Password menggunakan scrypt; SQL terparameterisasi. Rate limit saat ini per-IP/per-proses; jangan percaya forwarded headers tanpa konfigurasi trusted proxy yang diaudit.

## Validasi yang dapat diulang

```bash
python -m pip install -r requirements-signaling.txt -r requirements-platform.txt
PYTHONPATH=. python -m unittest discover -s tests -v
python -m compileall -q platform_app.py platform_core tests/test_platform.py
node --check platform_static/platform.js
python tools/check_template_js.py
```

Browser QA opsional memakai Node + Playwright 1.64.1 dan Chromium lokal. Gunakan database kosong untuk tiap run dan dua terminal dengan `WEWATCH_QA_DIR` yang sama:

```bash
export WEWATCH_QA_DIR="$(mktemp -d)"  # privat, mode 0700
python tools/run_platform_qa_server.py
# Terminal kedua: ekspor WEWATCH_QA_DIR yang sama.
# Siapkan dependency QA di luar repository (bukan dependency runtime):
npm install --prefix /tmp/wewatch-qa-deps playwright@1.64.1
NODE_PATH=/tmp/wewatch-qa-deps/node_modules CHROMIUM_PATH=/path/to/chromium \
  node tools/platform_browser_qa.cjs
```

Fixture server memiliki secret yang diketahui, rate limit nonaktif, hanya loopback. **Jangan deploy.** Output dan mailbox mengandung token fixture: jangan commit; hapus setelah uji. UI smoke test bukan sertifikasi WCAG atau uji seluruh browser.

## Release gates — NO-GO produksi publik

1. SMTP nyata (STARTTLS wajib), verified sending domain SPF/DKIM/DMARC, deliverability, retry/queue dan pengujian kegagalan. Pengiriman saat ini sinkron: response generik mengurangi enumerasi berbasis isi, tetapi perbedaan waktu delivery masih perlu diperkeras dengan async outbox.
2. SSO/MFA khususnya Owner/Admin, recovery policy, breached-password checks dan incident revocation workflow belum ada.
3. SQLite adalah pilot satu instance; isolasi berbasis aplikasi **bukan PostgreSQL RLS**. Perlu migrasi DB terkelola, backup/restore drill, distributed rate limiting, load/concurrency dan schema rollout untuk multi-instance.
4. TLS/reverse proxy/production WSGI, trusted proxy policy dan secrets manager belum divalidasi. `python platform_app.py` hanya server development. `PLATFORM_ENV=production` mewajibkan origin HTTPS, secure cookie dan SMTP host; lolos validasi konfigurasi bukan approval deploy.
5. Retention, account/workspace deletion/export, audit durability/alerting dan legal consent belum lengkap (tahap 4).
6. Pairing perangkat, consent granular, workspace/room/device binding, media/WebRTC/Windows/AI quality masih tahap 2–5. Tidak mengklaim platform utuh atau semua modul siap digunakan.
