# Roadmap Produk HR — WeWatch

**Status:** Discovery awal — profil pilot dan pilihan MVP tercatat; kebijakan detail serta batas verifikasi GPS/kamera masih perlu validasi  
**Terakhir diperbarui:** 2026-10-29  
**Tujuan:** Mencatat hasil kerja yang sudah dilakukan, visi produk HR, kandidat fitur, dan tahapan berikutnya. Roadmap ini adalah rencana; fitur HR di bawah belum diimplementasikan.

## 1. Visi dan batas produk

Bangun aplikasi HR yang membantu HR dan karyawan mengelola informasi, proses kerja, kehadiran, cuti, pengembangan, dan koordinasi proyek secara transparan. Produk harus menjadi alat administrasi dan dukungan—bukan sistem pengawasan rahasia atau penilai otomatis atas perilaku karyawan.

Repo saat ini adalah prototipe dashboard computer-vision, meeting, dan desktop-agent; repo ini belum merupakan HRIS. Perlakukan WeWatch sebagai kandidat modul opsional, bukan fondasi untuk mengumpulkan semua data karyawan. Fitur kamera, biometrik, inferensi mood/perhatian, deteksi penggunaan ponsel, dan screenshot memerlukan penilaian ulang tersendiri sebelum dipakai dalam konteks kerja. Jangan gunakan inferensi tersebut sebagai dasar tunggal untuk keputusan disiplin, perekrutan, promosi, atau kompensasi. Lihat [README](../README.md) dan [kebijakan privasi dan persetujuan](PRIVACY_AND_CONSENT.md).

## 2. Pekerjaan yang sudah dilakukan

| Tahap | Status | Hasil |
|---|---|---|
| Peninjauan dan audit teknis repo | Selesai | Mengidentifikasi risiko pada konfigurasi server, autentikasi, agent desktop, data sensitif, dan dependensi. Temuan serta panduan operasional dicatat di [Audit dan Operasional](AUDIT_AND_OPERATIONS.md). |
| Hardening keamanan dan privasi | Selesai | Menambahkan gate konfigurasi produksi, secret dan cookie yang lebih aman, perlindungan CSRF, pembatasan remote desktop, retensi/pembersihan data, pengaturan opt-in, pengamanan layanan infrastruktur, dan lock dependensi ber-hash. Commit: [46bb5a7](https://github.com/stmarya/WeWatch/commit/46bb5a7e663e540698a04c8b531a7cc49920d82a). |
| Review ulang dan tes kode | Selesai | 31 tes lulus; pemeriksaan compile Python, JavaScript template, YAML, whitespace, dan `pip-audit` lulus pada saat diperiksa. Validasi runtime Docker Compose serta uji TLS, TURN/LiveKit, beban media, dan hardware belum dilakukan. |
| Discovery awal HR | Berjalan | Profil awal: Indonesia, pilot kurang dari 50 karyawan, pola hybrid, jam reguler plus beberapa shift bergilir, web responsif, koreksi ditinjau HR, serta evaluasi WeWatch untuk presence opt-in. GPS/kamera diminta sebagai opsi, tetapi fungsi, momen penggunaan, safeguards, dan validasi aturan belum diputuskan. |

Status “Selesai” pada audit/hardening hanya berarti perubahan kode dan pemeriksaan yang disebutkan telah dilakukan; itu bukan persetujuan legal atau bukti kesiapan produksi. Detail privasi dan batas validasi ada di [dokumen privasi](PRIVACY_AND_CONSENT.md) dan [panduan operasional](AUDIT_AND_OPERATIONS.md).

## 3. Pengguna dan prinsip produk

**Pengguna utama:** karyawan, manajer, HR/admin, dan auditor terbatas. Hak akses harus berbeda berdasarkan peran dan kebutuhan kerja; karyawan dapat melihat data tentang dirinya, mengajukan koreksi, dan memahami siapa yang dapat mengakses datanya.

Prinsip wajib:

- Transparansi: jelaskan data apa yang dikumpulkan, tujuan, penerima, lokasi, dan masa simpan sebelum fitur diaktifkan.
- Minimasi data: kumpulkan hanya data yang dibutuhkan untuk proses HR yang jelas; jangan merekam layar/kamera secara terus-menerus sebagai default.
- Kendali dan koreksi: sediakan akses, koreksi, dan jalur keberatan bagi karyawan sesuai kebijakan organisasi.
- Keputusan manusia: metrik dan ringkasan hanya membantu peninjauan; keputusan berdampak pada karyawan perlu konteks dan penilaian manusia.
- Keamanan: least privilege, autentikasi kuat, audit akses/perubahan, enkripsi, retensi terbatas, dan proses penghapusan.
- Kepatuhan: validasi hukum ketenagakerjaan, privasi, biometrik, dan transfer lintas negara untuk yurisdiksi operasi sebelum pilot.

## 4. Kandidat fitur

### Fondasi HRIS

- Direktori karyawan dan struktur organisasi dengan field minimum yang disepakati.
- Profil serta status lifecycle karyawan: onboarding, perubahan peran, dan offboarding.
- Role-based access control, log audit, notifikasi, pencarian, dan ekspor yang dibatasi.
- Portal self-service untuk melihat profil sendiri, kebijakan, pengajuan, dan status permintaan.

### Operasional harian — kandidat MVP

Prioritas pertama adalah kehadiran dan jadwal/shift. Pilihan awal discovery: jam kerja reguler plus beberapa shift bergilir, pola hybrid, aplikasi web responsif untuk desktop dan browser ponsel, check-in/out mandiri, dan koreksi ditinjau HR. Aturan detail dan pengecualian masih perlu divalidasi bersama pengguna pilot.

GPS dan kamera diminta sebagai opsi, tetapi penggunaan persisnya belum ditetapkan. Usulan guardrail untuk dikonfirmasi: hanya pada kejadian check-in tertentu (bukan pelacakan/perekaman terus-menerus), opt-in terpisah dengan alternatif manual tanpa penalti, tujuan dan retensi yang jelas, serta tanpa pengenalan wajah/biometrik. Jangan aktifkan sebelum kajian privasi dan aturan setempat selesai.

Kandidat acceptance criteria untuk slice pertama (belum disetujui):

- Karyawan dapat melihat jadwal/catatan kehadiran dan melakukan check-in/out mandiri lewat web atau ponsel; karyawan dapat meminta koreksi.
- HR yang berwenang dapat meninjau dan memutuskan koreksi; perubahan dan keputusan tercatat.
- HR dapat mengatur kebijakan/jadwal yang disepakati serta melihat laporan sesuai hak akses.
- Akses manajer, data verifikasi, dan alur pengecualian ditetapkan setelah validasi; GPS/kamera tidak aktif secara default. Jika dipertimbangkan, gunakan hanya sesuai guardrail privasi yang disetujui, tanpa pengenalan wajah/biometrik, dan selalu sediakan metode manual.

Fitur operasional berikutnya dapat mencakup cuti/izin, onboarding/offboarding, dan dashboard proses HR. Hindari ranking karyawan berdasarkan sinyal pengawasan.

### Proyek dan pengembangan — kandidat tahap berikutnya

- Proyek, milestone, owner, dependensi, status, dan tindak lanjut.
- Tujuan kerja dan check-in berkala yang disepakati karyawan/manajer.
- 1:1, umpan balik, evaluasi kinerja terstruktur, dan rencana pengembangan.
- Pelatihan/kompetensi dan integrasi dengan sistem payroll atau identitas hanya setelah kebutuhan dan batas akses disepakati.

### WeWatch sebagai modul opsional

Jika kebutuhan dan kajian kebijakan membenarkannya, evaluasi modul check-in/presence yang terpisah dan eksplisit opt-in. Batasi tujuan, akses, dan retensinya; sediakan cara menolak/berhenti dan audit penggunaan. Jangan mengirim foto mentah atau inferensi wajah, mood, kantuk, perhatian, maupun penggunaan ponsel ke skor kinerja HR. Rekomendasi awal: mulai tanpa biometrik dan tanpa screenshot; pertimbangkan ulang hanya dengan kebutuhan sah yang terdokumentasi, penilaian risiko, persetujuan yang sesuai, dan uji coba terbatas.

## 5. Roadmap yang diusulkan

Urutan di bawah adalah tahapan, bukan tanggal rilis. Estimasi dan target baru ditetapkan setelah discovery dan persetujuan ruang lingkup.

| Tahap | Status | Hasil yang dituju / gerbang keluar |
|---|---|---|
| 0. Audit repo dan hardening dasar | Selesai | Risiko teknis awal ditangani pada kode; tes dan audit dependensi dijalankan. Catatan batas validasi tetap terbuka di dokumen operasional. |
| 1. Discovery HR dan tata kelola | Berjalan — discovery awal | Profil awal: Indonesia, pilot kurang dari 50 karyawan, hybrid, jam reguler plus beberapa shift bergilir, web responsif, check-in/out mandiri, koreksi ditinjau HR, serta kajian presence opt-in. GPS/kamera masih opsi yang perlu dibatasi dan dikaji. Validasi alur, aturan, retensi, akses, dan kebutuhan bersama HR/karyawan sebelum backlog disetujui. |
| 2. Desain produk dan arsitektur | Direncanakan | Persona, alur pengguna, model data minimum, matriks akses, threat model, keputusan hosting/residensi, prototipe UI, dan acceptance criteria MVP disetujui. |
| 3. Fondasi HRIS | Direncanakan | Login/SSO sesuai kebutuhan, organisasi, direktori, profil, RBAC, audit log, retensi, dan self-service dasar; uji keamanan dan akses per peran. |
| 4. MVP operasional HR | Direncanakan | Kandidat slice pertama: jam reguler plus beberapa shift bergilir; web responsif; check-in/out mandiri; catatan kehadiran; koreksi yang ditinjau HR. GPS/kamera tetap mati secara default sampai cakupan, pilihan karyawan, alternatif, retensi, dan kajian aturan disetujui. |
| 5. Proyek dan pengembangan | Direncanakan | Milestone, check-in, tujuan, 1:1, feedback, dan laporan agregat; tinjau fairness dan akses sebelum dipakai untuk keputusan. |
| 6. Evaluasi modul WeWatch | Kajian opt-in dipilih; implementasi belum disetujui | Evaluasi check-in/presence yang transparan dan opt-in saja, bandingkan dengan metode yang kurang invasif, dan tinjau tujuan, aturan setempat, dampak, consent, keamanan, serta retensi. Jangan aktifkan kamera/biometrik/inferensi perilaku sebagai default; pilot hanya jika seluruh gerbang disetujui. |
| 7. Pilot, integrasi, dan rollout | Direncanakan | Uji penerimaan, aksesibilitas, keamanan, backup/pemulihan, beban, dukungan, prosedur insiden, serta metrik manfaat dan kepercayaan sebelum perluasan. |

## 6. Cara melacak progres

Untuk setiap perubahan roadmap, catat tanggal, status (`Direncanakan`, `Berjalan`, `Terblokir`, atau `Selesai`), hasil/artefak, bukti validasi, risiko yang tersisa, dan keputusan berikutnya. Jangan menandai tahap selesai hanya karena kode sudah dibuat: gerbang pengujian, kebijakan, dan penerimaan pengguna juga harus terpenuhi.

Indikator awal yang perlu ditetapkan baseline-nya saat discovery: waktu penyelesaian proses HR, ketepatan data, waktu penyelesaian koreksi kehadiran, adopsi self-service, kepuasan/kepercayaan pengguna, serta jumlah insiden keamanan/privasi. Tetapkan target setelah baseline tersedia; jangan menjadikan aktivitas kamera atau estimasi produktivitas individu sebagai KPI.

## 7. Keputusan discovery yang sudah dicatat

Berdasarkan jawaban awal pemilik proyek pada 2026-10-29:

- Yurisdiksi pilot: Indonesia. Detail aturan ketenagakerjaan dan privasi tetap perlu diverifikasi sebelum uji coba.
- Ukuran organisasi/grup pilot: kurang dari 50 karyawan.
- Pola kerja: hybrid; pola jadwal: jam reguler plus beberapa shift bergilir.
- Prioritas MVP: kehadiran dan jadwal/shift.
- Platform: web responsif untuk desktop dan browser ponsel.
- Metode: check-in/out mandiri via web/ponsel.
- GPS dan kamera diminta sebagai opsi; momen penggunaan, data yang diambil, dasar/persetujuan, alternatif tanpa penalti, akses, dan retensi belum disetujui. Default tetap nonaktif; tidak ada pelacakan terus-menerus atau pengenalan wajah/biometrik.
- Koreksi catatan kehadiran: ditinjau HR.
- WeWatch: evaluasi jalur check-in/presence yang transparan dan opt-in saja. Ini bukan persetujuan untuk mengaktifkan kamera, biometrik, screenshot, atau pemantauan terus-menerus.

## 8. Keputusan discovery berikutnya

1. Bagaimana jadwal campuran dibentuk: jadwal tetap/bergilir/fleksibel, hari kerja, zona waktu, lokasi, istirahat, toleransi keterlambatan, dan lembur.
2. Tentukan tujuan dan batas opsi GPS/kamera: apakah hanya saat check-in, data apa yang diambil, siapa yang melihat, berapa lama disimpan, dan bagaimana tersedia alternatif manual tanpa penalti. Default usulan: tidak ada pelacakan/perekaman terus-menerus, GPS/kamera nonaktif kecuali diaktifkan secara sadar setelah kajian, serta tidak ada pengenalan wajah/biometrik. Untuk pola hybrid, validasi kebutuhan ini terhadap opsi self-report yang lebih minim data.
3. HR dipilih untuk meninjau koreksi; tentukan delegasi, bukti yang dibutuhkan, tenggat, alasan penolakan, eskalasi, dan jalur keberatan.
4. Jenis data, masa simpan, akses, ekspor, dan penghapusan yang sesuai kebijakan serta aturan Indonesia yang telah diverifikasi.
5. Perwakilan HR, manajer, dan karyawan yang akan memvalidasi alur dan ikut pilot.
6. Kebutuhan integrasi, hosting/residensi data, dan batas MVP yang benar-benar diperlukan.
