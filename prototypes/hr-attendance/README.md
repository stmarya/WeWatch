# WeWatch HR — Attendance Prototype

Prototipe lokal untuk meninjau alur jadwal, check-in/out, opsi sensor, dan koreksi HR. Ini bukan fitur produksi atau kebijakan absensi. Semua karyawan/jadwal pada `sample_data.json` bersifat fiktif.

## Skenario jadwal demo (usulan, bukan kebijakan)

- **Office hours:** Senin–Jumat, 09:00–18:00 WIB, dengan asumsi jeda 60 menit.
- **Cakupan 24/7:** tiga template 8 jam setiap hari: 06:00–14:00, 14:00–22:00, dan 22:00–06:00 hari berikutnya. Shift malam berakhir pada tanggal kalender berikutnya.
- Penugasan karyawan bersifat statis dan sintetis. Rotasi, hari libur, jumlah staf, jeda/relief, toleransi keterlambatan, lembur, dan payroll tidak dimodelkan atau ditetapkan.
- Semua jam adalah bahan walkthrough yang perlu disesuaikan dan disetujui HR sebelum dipakai sebagai aturan pilot.

## Menjalankan

Dari root repo:

```bash
python -m http.server 8765 --directory prototypes/hr-attendance
```

Buka `http://localhost:8765` di browser. Browser modern membatasi akses GPS/kamera pada konteks aman; `localhost` dipakai untuk uji lokal. Jangan mengekspos server demo ini ke internet atau jaringan publik.

## Sensor dalam demo

- GPS dan kamera mati sampai peserta memilih opsi dan memulai tindakan check-in/out. Browser tetap akan meminta izin perangkat.
- GPS menggunakan satu panggilan `getCurrentPosition`; prototipe tidak memakai `watchPosition` atau tracking latar belakang.
- Kamera hanya menampilkan preview lokal; saat check-in demo, stream diuji lalu dihentikan. Tidak ada pengambilan frame, audio, pengenalan wajah, pengiriman gambar, atau penyimpanan media.
- Check-in/out sesi hanya berada di memori tab; refresh/menutup tab menghapusnya. Tidak ada database, API, `localStorage`, atau analytics pihak ketiga.
- Sediakan uji manual tanpa sensor. Uji sensor hanya pada perangkat sendiri atau dengan peserta yang diberi penjelasan dan memilih ikut.

Seed GPS memakai koordinat sintetis `(0, 0)` sebagai data uji, bukan lokasi kantor. Jadwal dan status hanya contoh; jangan gunakan sebagai aturan kerja nyata.
