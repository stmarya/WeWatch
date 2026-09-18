# Ultimate Watcher (Super Face & Body Analysis V2.0)

Sebuah aplikasi Desktop AI terpadu menggunakan Computer Vision, MediaPipe, dan Face Recognition.

## Fitur Utama:
1. **Pendeteksi Kantuk**: Alarm visual di layar jika mata tertutup lebih dari 1.5 detik.
2. **Kacamata AR**: Filter *Augmented Reality* yang melacak koordinat iris mata dan menempelkan kacamata 3D/2D secara *real-time*.
3. **Virtual Mouse**: Mengontrol kursor mouse menggunakan hidung, dan melakukan klik kiri melalui kedipan mata yang disengaja.
4. **Identitas Wajah**: Mengenali wajah Anda (Pemilik) dari file `wajah_saya.jpg`.
5. **Hand Gestures**: Melacak kerangka tangan. Acungkan jempol (Thumbs Up) untuk mengambil *Screenshot* layar secara otomatis!
6. **Background Blur**: Mengaburkan latar belakang di belakang Anda secara *real-time* seperti fitur kamera Zoom.
7. **Analisis Postur**: Melacak postur tulang belakang dan bahu Anda. Memunculkan peringatan jika Anda duduk terlalu membungkuk di depan layar.
8. **Mode Keamanan (Smart Recording)**: Jika mode ini diaktifkan dan wajah tidak dikenal (Penyusup) terdeteksi, AI secara otomatis merekam video `.avi` secara rahasia di latar belakang.

## Persyaratan
- Python 3.9+
- `pip install -r requirements.txt`
- Letakkan foto wajah Anda sendiri di folder yang sama dan beri nama `wajah_saya.jpg`.

## Cara Menjalankan
```bash
python main.py
```
Gunakan panel kontrol di sebelah kanan layar (GUI) untuk menyalakan atau mematikan modul AI.
