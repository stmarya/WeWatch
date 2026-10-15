# WeWatch — Urutan Eksekusi Platform

Setiap tahap memiliki PR, bukti tes, dan release gate. Jangan menandai seluruh platform selesai hanya karena fondasi akun berjalan.

| Tahap | Ruang lingkup | Status | Gate berikutnya |
| --- | --- | --- | --- |
| 1 — Identitas & workspace | Register, verifikasi, login/reset, sesi, workspace, undangan, RBAC, isolasi control plane | Core pilot diimplementasikan; review/merge tertunda | Review PR bertumpuk setelah audit PR #3; SMTP nyata, SSO/MFA dan infra produksi tetap terbuka |
| 2 — Onboarding & izin | Wizard perangkat, device readiness, pairing workspace, consent kamera/mikrofon/remote terpisah, revoke | Belum dikerjakan | Tidak ada akses sebelum consent; perangkat terikat workspace dan user |
| 3 — Integrasi modul inti | Meeting/room, AI lokal, desktop agent, semua entrypoint dan status ketersediaan | Belum dikerjakan | Otorisasi server-side tiap room/device; degraded states; jangan jadikan role Host izin remote otomatis |
| 4 — Admin & operasi | User/device/session management, kebijakan fitur, retention/deletion/export, audit/alerting | Belum dikerjakan | Least privilege, non-sensitive telemetry, recovery dan backup teruji |
| 5 — Validasi produksi | Windows/perangkat nyata, kamera/mikrofon, WebRTC/TURN, security/load/soak, AI benchmark | Belum dikerjakan | Semua gate NO-GO ditutup dengan bukti, rollback dan observability |
| 6 — Eksperimen & monetisasi | Paket/entitlement/billing dan eksperimen berizin | Belum dikerjakan | Tidak memonetisasi inferensi biometrik atau penilaian kinerja yang tidak tervalidasi |

## Handoff tahap 2

- Mulai dari akun terverifikasi dan workspace yang dipilih secara eksplisit.
- Buat inventory capability/OS/model, dengan status unavailable/disabled/ready yang jujur.
- Pairing sekali pakai, TTL, device identity dan scope workspace; dapat dicabut dari kedua sisi.
- Preview kamera/mikrofon hanya setelah tindakan pengguna; izin media tidak berarti izin remote.
- Consent remote mencantumkan kapabilitas, durasi, indikator aktif dan tombol stop darurat; gagal koneksi/timeout harus menghentikan kontrol.
- Uji outsider/cross-tenant, role downgrade, revoke, replay, offline, model hilang dan permission denied sebelum menghubungkan layanan lama.

Panduan setup, RBAC dan batas implementasi tahap 1: [PLATFORM_PHASE_1.md](PLATFORM_PHASE_1.md).
