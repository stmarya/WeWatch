# WeWatch HR — Attendance Prototype

Prototipe lokal untuk meninjau alur jadwal, check-in/out, opsi sensor, dan koreksi HR. Ini bukan fitur produksi atau kebijakan absensi. Semua karyawan/jadwal pada `sample_data.json` bersifat fiktif.

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
