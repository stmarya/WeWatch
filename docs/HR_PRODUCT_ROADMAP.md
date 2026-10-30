# Roadmap Produk HR — WeWatch

**Status:** Prototipe lokal dengan data sintetis siap diuji; persetujuan sensor hanya untuk uji tindakan eksplisit, kebijakan produksi masih menunggu validasi  
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
| Prototipe lokal dan data sintetis | Siap diuji lokal | Demo mandiri di [prototypes/hr-attendance](../prototypes/hr-attendance/README.md) memakai 8 profil fiktif, 4 template jadwal, 8 catatan, dan 3 koreksi. GPS satu kali/kamera preview hanya setelah tindakan dan opt-in; tidak ada database, media tersimpan, atau koneksi ke HR produksi. |
| Validasi prototipe | Lulus untuk smoke-test lokal | 3 tes prototipe lulus; pemeriksaan syntax JavaScript, JSON, HTML, dan render Chromium lokal lulus. GPS/kamera fisik belum diuji. Percobaan suite penuh pada sesi terakhir terhenti karena environment tidak memiliki `flask` dan `socketio`; bukan kegagalan assertion prototipe. |
| Draft kebutuhan dan kesiapan MVP | Siap untuk review | Draft alur kehadiran, cerita pengguna, peran, guardrail data, dan gerbang sebelum coding ada pada bagian 9. Belum disetujui HR/karyawan dan belum menjadi fitur produksi. |
| Discovery awal HR | Berjalan | Profil pilot dan guardrail awal sudah dicatat; pencarian tidak menemukan kebijakan HR/absensi internal. Detail jadwal, retensi, akses, dan kajian aturan masih menunggu validasi HR/karyawan. |

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

Batas yang dipilih untuk rancangan: GPS/kamera hanya pada check-in/out yang dimulai karyawan; opt-in terpisah; selalu tersedia alternatif manual tanpa penalti; tanpa pengenalan wajah/biometrik dan tanpa pelacakan/perekaman terus-menerus. Sebelum implementasi, tetap tetapkan tujuan, data persis yang diproses, siapa yang mengakses, masa simpan, pilihan nyata karyawan, dan hasil kajian privasi serta aturan setempat.

Kandidat acceptance criteria untuk slice pertama (belum disetujui):

- Karyawan dapat melihat jadwal/catatan kehadiran dan melakukan check-in/out mandiri lewat web atau ponsel; karyawan dapat meminta koreksi.
- HR yang berwenang dapat meninjau dan memutuskan koreksi; perubahan dan keputusan tercatat.
- HR dapat mengatur kebijakan/jadwal yang disepakati serta melihat laporan sesuai hak akses.
- Akses manajer, data verifikasi, dan alur pengecualian ditetapkan setelah validasi. GPS/kamera hanya dapat dipertimbangkan pada check-in/out yang dimulai karyawan, dengan opt-in terpisah dan alternatif manual; tanpa pengenalan wajah/biometrik atau pelacakan terus-menerus, serta belum boleh diaktifkan sebelum kajian kebijakan selesai.

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
| 1. Discovery HR dan tata kelola | Berjalan — discovery awal | Profil awal: Indonesia, pilot kurang dari 50 karyawan, hybrid, jam reguler plus beberapa shift bergilir, web responsif, check-in/out mandiri, dan koreksi ditinjau HR. Guardrail GPS/kamera untuk prototipe telah dipilih; validasi aturan, kebijakan, retensi, akses, dan kebutuhan HR/karyawan tetap pending untuk pilot/produksi. |
| 2. Desain produk dan arsitektur | Berjalan — prototipe lokal | Draf user stories dan checklist kesiapan ada pada bagian 9; demo lokal serta [seed data sintetis](../prototypes/hr-attendance/sample_data.json) sudah tersedia untuk uji alur. Finalisasi produksi menunggu kebijakan HR, validasi pilot, kajian aturan dan keputusan akses/retensi/hosting. |
| 3. Fondasi HRIS | Direncanakan | Login/SSO sesuai kebutuhan, organisasi, direktori, profil, RBAC, audit log, retensi, dan self-service dasar; uji keamanan dan akses per peran. |
| 4. MVP operasional HR | Direncanakan | Kandidat slice pertama: jam reguler plus beberapa shift bergilir; web responsif; check-in/out mandiri; catatan kehadiran; koreksi yang ditinjau HR. Jika kajian menyetujui, GPS/kamera hanya pada check-in/out yang dimulai karyawan, opt-in terpisah, dengan alternatif manual; tanpa pengenalan wajah/biometrik atau pelacakan terus-menerus. |
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
- Batas GPS/kamera yang dipilih: hanya pada check-in/out yang dimulai karyawan, opt-in terpisah, alternatif manual tanpa penalti, tanpa pengenalan wajah/biometrik atau pelacakan terus-menerus. Prototipe lokal boleh menguji alur browser ini tanpa menyimpan/mengirim data; penggunaan pada pilot/produksi menunggu kajian tujuan, data, dasar/persetujuan, akses, dan retensi.
- Koreksi catatan kehadiran: ditinjau HR.
- WeWatch: evaluasi jalur check-in/presence yang transparan dan opt-in saja. Ini bukan persetujuan untuk mengaktifkan kamera, biometrik, screenshot, atau pemantauan terus-menerus.

## 8. Keputusan discovery berikutnya

1. Bagaimana jadwal campuran dibentuk: jadwal tetap/bergilir/fleksibel, hari kerja, zona waktu, lokasi, istirahat, toleransi keterlambatan, dan lembur.
2. Batas penggunaan sudah dipilih: hanya pada check-in/out yang dimulai karyawan, opt-in terpisah, alternatif manual tanpa penalti, tanpa pengenalan wajah/biometrik atau pelacakan terus-menerus. Sebelum implementasi, tentukan tujuan, data persis, siapa yang mengakses, retensi, dasar/persetujuan, cara menolak tanpa dampak merugikan, dan verifikasi alternatif yang lebih minim data untuk kerja hybrid.
3. HR dipilih untuk meninjau koreksi; tentukan delegasi, bukti yang dibutuhkan, tenggat, alasan penolakan, eskalasi, dan jalur keberatan.
4. Jenis data, masa simpan, akses, ekspor, dan penghapusan yang sesuai kebijakan serta aturan Indonesia yang telah diverifikasi.
5. Perwakilan HR, manajer, dan karyawan yang akan memvalidasi alur dan ikut pilot.
6. Kebutuhan integrasi, hosting/residensi data, dan batas MVP yang benar-benar diperlukan.

## 9. Kesiapan MVP: prototipe lokal siap; build produksi menunggu validasi

Pencarian pada Notion untuk kebijakan kehadiran/jadwal dan peninjauan dokumen repo tidak menemukan kebijakan HR internal yang dapat dijadikan sumber aturan. Karena itu bagian ini adalah **draf produk untuk divalidasi**, bukan kebijakan perusahaan atau nasihat hukum. Jawaban pemilik proyek menentukan arah awal, tetapi belum menggantikan persetujuan HR dan umpan balik karyawan. Prototipe terisolasi dan instruksi uji lokal tersedia di [prototipe kehadiran](../prototypes/hr-attendance/README.md); seed data ada di [sample_data.json](../prototypes/hr-attendance/sample_data.json).

### Bagian yang sudah siap untuk walkthrough

- **Target pilot:** Indonesia, kelompok di bawah 50 karyawan, pola kerja hybrid.
- **Slice MVP:** jadwal jam reguler ditambah beberapa shift bergilir; check-in/out mandiri; HR meninjau koreksi.
- **Platform awal:** web responsif untuk desktop dan browser ponsel.
- **Guardrail verifikasi:** GPS/kamera hanya pada check-in/out yang dimulai karyawan; opt-in terpisah; alternatif manual tanpa penalti; tanpa pengenalan wajah/biometrik dan pelacakan/perekaman terus-menerus.
- **Batas status:** siap untuk walkthrough dan uji lokal dengan data fiktif. GPS diminta satu kali dan kamera dipakai untuk preview/smoke-test hanya setelah tindakan/opt-in; tidak ada penyimpanan atau transfer. Ini belum integrasi HR, bukan pengganti persetujuan setiap peserta, belum pilot operasional karyawan, dan belum siap produksi.

### Draf alur dan acceptance criteria

| Alur | Kriteria awal untuk divalidasi |
|---|---|
| Jadwal | HR dapat membuat jadwal reguler dan beberapa template shift bergilir, lalu menugaskannya ke karyawan/tim. Karyawan dapat melihat jadwalnya sendiri. Aturan jam, zona waktu, hari libur, istirahat, dan lembur belum ditetapkan. |
| Check-in/out | Karyawan memulai check-in dan check-out sendiri melalui web responsif. Karyawan dapat melihat catatan miliknya. Check-in manual tetap tersedia meskipun opsi GPS/kamera ditolak atau tidak tersedia. |
| Koreksi | Karyawan mengajukan koreksi dengan waktu yang diminta dan alasan. HR yang berwenang menyetujui/menolak, menambahkan alasan keputusan, dan sistem menyimpan riwayat perubahan serta menampilkan status kepada karyawan. Tenggat dan eskalasi masih perlu disepakati. |
| Laporan | HR melihat catatan sesuai cakupan tugasnya. Akses manajer, batas data tim, unduhan, dan agregasi harus diputuskan sebelum desain final. Hindari ranking produktivitas individu. |
| GPS/kamera opsional | Hanya pada tindakan check-in/out yang dimulai karyawan, opt-in per fitur, dengan jalur manual tanpa penalti. Tidak ada pengenalan wajah, pelacakan berkelanjutan, atau penyimpanan bukti mentah sebelum tujuan, akses, retensi, dan kajian aturan disetujui. |
| Audit dan kontrol | Catat siapa mengubah jadwal, mengoreksi catatan, atau menyetujui permintaan dan kapan. Batasi akses berdasarkan peran; karyawan dapat melihat data dan status koreksinya sendiri. |

### Matriks akses awal — perlu persetujuan

| Peran | Akses yang diusulkan | Yang masih perlu diputuskan |
|---|---|---|
| Karyawan | Lihat jadwal/catatan sendiri; check-in/out; minta koreksi; lihat keputusan. | Akses atas data verifikasi opsional dan cara mengunduh/meminta penghapusan. |
| HR | Atur jadwal dalam cakupan kerja; lihat catatan yang diperlukan; tinjau koreksi dan jalankan laporan terbatas. | Cakupan HR per unit, delegasi, pemisahan tugas, ekspor, dan akses ke data GPS/kamera. |
| Manajer | Belum ditetapkan; usulan awal hanya ringkasan/jadwal tim yang dibutuhkan. | Apakah perlu akses, data apa, dan apakah tidak boleh melihat bukti GPS/kamera. |
| Admin sistem | Kelola akun, konfigurasi, dan peran. | Prosedur akses darurat, persetujuan, pencatatan, dan pembatasan akses ke data HR. |

### Gerbang sebelum implementasi

- [ ] HR menyetujui aturan jadwal reguler/shift, zona waktu, istirahat, keterlambatan, absensi, hari libur, dan lembur.
- [ ] HR menyetujui alur koreksi: alasan yang diperlukan, siapa yang memutuskan, tenggat, eskalasi, dan cara karyawan mengajukan keberatan.
- [ ] Perwakilan karyawan/pilot meninjau alur, pemberitahuan, self-service, dan alternatif manual.
- [ ] Tetapkan data minimum, akses per peran, retensi, penghapusan, backup, dan batas ekspor.
- [ ] Untuk pemakaian GPS/kamera dalam pilot HR atau produksi, dokumentasikan tujuan, data yang tepat, dasar pemrosesan/persetujuan yang sesuai, pilihan nyata tanpa penalti, akses, retensi, dan alternatif lebih minim data; minta review pihak yang memahami aturan Indonesia sebelum mengaktifkan. Uji lokal saat ini hanya memakai browser API setelah tindakan/opt-in dan tidak menyimpan atau mengirim datanya.
- [ ] Setujui arsitektur, autentikasi, audit log, threat model, hosting/residensi, pemulihan, dan kriteria uji sebelum membuat fitur.

**Keputusan readiness saat ini:** prototipe lokal siap dipakai untuk meninjau pengalaman dan sensor dengan data sintetis serta peserta yang secara sadar memilih ikut. Belum siap untuk pilot operasional karyawan, menyimpan data sensor, menetapkan aturan absensi final, atau mengklaim kepatuhan hukum. Backlog implementasi produksi menunggu validasi HR/karyawan dan gerbang di atas.

## 10. Snapshot progres dan tindak lanjut

**Pengecekan terakhir:** 2026-10-29. Status ini merangkum bukti yang tersedia di repo dan pengujian prototipe lokal; belum ada sign-off dari HR atau peserta pilot.

| Area | Status sekarang | Bukti / tindak lanjut |
|---|---|---|
| Audit awal dan hardening dasar | Selesai untuk baseline kode | Catatan audit dan commit hardening ada di bagian 2; beberapa validasi deployment masih di luar cakupan. |
| Definisi awal produk dan discovery | Berjalan | Pilot, tujuan MVP, platform, alur koreksi, dan guardrail sensor sudah dicatat dari jawaban pemilik proyek. Validasi HR/karyawan dan aturan internal belum ada. |
| Data dan UX prototipe | Siap untuk uji lokal | Seed sintetis dan halaman demo tersedia; 3 tes khusus, syntax/format, dan render lokal lulus. Sensor hardware nyata belum dicoba. |
| Kebijakan kehadiran dan hak akses | Belum disetujui | Jam, istirahat, hari libur, keterlambatan/lembur, delegasi HR, akses manajer, SLA koreksi, serta masa simpan masih perlu keputusan organisasi. |
| Build HRIS/MVP produksi | Belum dimulai | Belum ada backend HR, autentikasi HR, database produksi, ekspor payroll, atau integrasi perangkat. Jangan perlakukan demo sebagai sistem operasional. |
| Pilot dan kesiapan produksi | Belum siap | Menunggu kebijakan dan review privasi/aturan, validasi dengan pengguna, arsitektur, uji keamanan/integrasi, serta persetujuan data dan sensor. |

### Urutan kerja berikutnya

1. Walkthrough alur jadwal dan absensi dengan HR serta perwakilan karyawan; tetapkan aturan yang dipakai pada pilot.
2. Setujui matriks akses dan alur koreksi/keberatan, termasuk apa yang boleh dilihat HR dan manajer.
3. Definisikan data minimum, retensi, penghapusan, dan tinjauan GPS/kamera untuk pilot/produksi.
4. Ubah acceptance criteria yang sudah disepakati menjadi backlog kecil, lalu implementasikan backend HR terpisah dari demo lokal.
5. Jalankan uji integrasi, akses berbasis peran, keamanan, dan uji sensor dengan peserta yang mengetahui serta memilih ikut sebelum pilot.

**Gerbang selesai:** tahap pilot baru dapat ditandai siap setelah aturan disetujui, alur diuji HR/karyawan, akses/retensi ditetapkan, temuan keamanan ditutup, dan semua skenario pilot lulus. Persentase progres belum ditetapkan karena baseline ruang lingkup dan target organisasi belum disepakati.

## 11. Backlog awal untuk melanjutkan pengembangan

Backlog ini diturunkan dari pilihan discovery yang sudah dicatat. Status `Terblokir` berarti keputusan/policy dari organisasi diperlukan; jangan menggantinya dengan asumsi kode. Tugas produksi tidak dianggap selesai hanya karena demo lokal berfungsi.

| ID | Prioritas | Kegiatan | Status | Kriteria keluar |
|---|---|---|---|---|
| DISC-01 | P0 | Validasi jam reguler, shift 24/7 tiga kali sehari, zona waktu, hari kerja/libur, istirahat, keterlambatan, dan lembur. | Berjalan — skenario awal di Bagian 12 menunggu review | HR/pemilik kebijakan meninjau dan menyetujui aturan pilot tertulis; batas asumsi dan isu terbuka dicatat. |
| DISC-02 | P0 | Walkthrough proses karyawan–HR: jadwal office hours dan 3 shift, check-in/out, koreksi, keberatan, notifikasi. | Siap untuk walkthrough skenario | HR dan perwakilan karyawan meninjau skenario Bagian 12, alur, serta acceptance criteria. |
| PRIV-01 | P0 | Definisikan data minimum, akses, retensi/penghapusan, pemberitahuan, dan penggunaan GPS/kamera untuk pilot/produksi. | Berjalan — guardrail demo ada; keputusan produksi pending | Data map, pilihan nyata tanpa penalti, dasar pemrosesan yang sesuai, akses dan retensi disetujui; kajian aturan Indonesia selesai. |
| UX-01 | P1 | Uji prototipe lokal pada desktop dan browser ponsel dengan data sintetis; catat hambatan pengguna. | Siap diuji | Umpan balik dicatat; uji sensor hanya dengan peserta yang mengetahui dan memilih ikut. |
| ARCH-01 | P1 | Tetapkan schema HR minimal, autentikasi, RBAC, audit log, timezone, hosting, backup, dan batas integrasi. | Terblokir oleh DISC-01/02/PRIV-01 | Dokumen arsitektur dan threat model disetujui sebelum backend dibuat. |
| BUILD-01 | P1 | Bangun direktori karyawan dan konfigurasi jadwal reguler/shift. | Belum dimulai | Hak akses dan kebijakan jadwal disetujui; tes per role lulus. |
| BUILD-02 | P1 | Bangun check-in/out mandiri serta tampilan catatan karyawan. | Belum dimulai | Timestamp, zona waktu, koreksi, fallback manual, dan audit trail memenuhi acceptance criteria. |
| BUILD-03 | P1 | Bangun pengajuan koreksi dan antrean review HR. | Belum dimulai | Keputusan HR beralasan, tercatat, dan status terlihat oleh karyawan. |
| QA-01 | P1 | Tes keamanan, aksesibilitas, integrasi, browser/device, backup/restore, dan sensor pada staging. | Berjalan — tes lokal parsial | Semua skenario uji lulus; uji hardware nyata terdokumentasi; tidak ada severity tinggi terbuka. |
| PILOT-01 | P2 | Pilot terbatas dengan data nyata setelah persetujuan dan kesiapan operasional. | Belum dimulai | Kebijakan, pemberitahuan, dukungan, akses, retensi, dan prosedur insiden disetujui; pemilik pilot sign-off. |

### Fokus kerja berikutnya

Mulai dari `UX-01` dan `DISC-01/02`: gunakan skenario usulan Bagian 12 sebagai bahan walkthrough dengan HR/peserta pilot; tandai tiap asumsi yang disetujui, diubah, atau ditolak. Sambil menunggu, data sensor produksi, perhitungan keterlambatan/lembur, dan keputusan yang berdampak pada karyawan tetap nonaktif. Setelah DISC/PRIV selesai, backlog teknis dapat dipastikan dan implementasi HRIS dimulai.

## 12. Skenario jadwal awal untuk prototyping (usulan, belum menjadi kebijakan)

Pemilik proyek mengarahkan bahwa sebagian tim bekerja office hours dan tim lainnya perlu cakupan 24/7 dalam tiga shift sehari. Karena belum ada aturan internal, angka di bawah adalah **asumsi awal untuk diuji dan disesuaikan**, bukan kebijakan perusahaan, perhitungan kepatuhan, atau dasar payroll. Zona waktu contoh: `Asia/Jakarta`.

### A. Tim office hours

- Hari contoh: Senin–Jumat.
- Jadwal contoh: 09:00–18:00 WIB dengan asumsi jeda 60 menit.
- Jadwal ini dapat dipakai tim kantor maupun hari kerja anggota tim hybrid; lokasi kerja tidak mengubah jadwal.
- Jeda, hari kerja, hari libur, fleksibilitas jam, dan perlakuan terhadap keterlambatan tetap perlu diputuskan HR.

### B. Tim layanan 24/7 — tiga shift harian

| Kode contoh | Jam lokal | Durasi rentang | Catatan |
|---|---|---:|---|
| Pagi | 06:00–14:00 | 8 jam | Berlaku setiap hari dalam skenario cakupan. |
| Sore | 14:00–22:00 | 8 jam | Berlaku setiap hari dalam skenario cakupan. |
| Malam | 22:00–06:00 hari berikutnya | 8 jam | Check-out jatuh pada tanggal kalender berikutnya; tanggal kerja mengikuti tanggal mulai shift untuk kebutuhan demo. |

- Tiga rentang itu membentuk contoh cakupan 24 jam; **bukan** berarti satu karyawan bekerja setiap hari atau jumlah kru cukup hanya tiga orang.
- Prototipe memakai template shift dan penugasan statis. Hari libur, kebutuhan orang per shift, pergantian/rotasi, waktu serah-terima, jeda dan petugas pengganti belum dimodelkan.
- Untuk demo rotasi di masa berikutnya, kandidat yang bisa dibahas adalah rotasi maju pagi → sore → malam. Frekuensi rotasi, hari istirahat dan jeda minimum antar-shift wajib ditinjau HR terlebih dahulu; jangan aktifkan perhitungan otomatis sebelum disetujui.

### C. Perilaku absensi sementara untuk uji UX

- Karyawan melihat jadwalnya sendiri dan memulai check-in/out; timestamp ditampilkan dalam WIB.
- Catatan yang hilang, checkout yang terlewat, dan permintaan koreksi masuk ke tinjauan manusia; jangan otomatis menyimpulkan mangkir atau memberi sanksi.
- Status “terlambat”, toleransi, lembur, pemotongan istirahat, dan dampak ke payroll belum dihitung karena aturannya belum disepakati.
- Koreksi diajukan karyawan dan ditinjau HR dengan alasan keputusan tercatat. Opsi manual tetap tersedia tanpa GPS/kamera.
- GPS/kamera tetap mengikuti guardrail sebelumnya: tindakan eksplisit, opt-in terpisah, tanpa pelacakan terus-menerus, tanpa pengenalan wajah, serta bukan syarat untuk mencatat kehadiran.

### D. Hal yang perlu dikonfirmasi sebelum skenario menjadi aturan pilot

1. Apakah jam office hours, hari kerja, serta asumsi jeda 60 menit cocok untuk tim pilot?
2. Apakah batas tiga shift 06–14, 14–22, 22–06 dan zona waktu WIB cocok; bagaimana aturan shift lintas tengah malam dicatat?
3. Berapa kebutuhan staf per shift, pola hari kerja/libur, mekanisme pengganti saat jeda, serah-terima, dan rotasi yang aman?
4. Bagaimana toleransi keterlambatan, absensi, koreksi, lembur, istirahat, dan eskalasi akan diperlakukan?
5. Siapa dari HR/manajer/karyawan yang menyetujui aturan tertulis sebelum pilot?

**Gerbang:** skenario ini boleh dipakai untuk walkthrough dan data sintetis. Sebelum menjadi kebijakan pilot atau memengaruhi penggajian/keputusan karyawan, semua asumsi perlu disetujui organisasi dan diverifikasi terhadap aturan yang berlaku.
