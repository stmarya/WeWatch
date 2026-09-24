import cv2
import time
import os

print("--- REGISTRASI WAJAH (FACE ID) ---")
nama_user = input("Masukkan nama Anda: ").strip()
if not nama_user:
    nama_user = "user_default"
    
print("Kamera akan menyala dalam 2 detik...")
time.sleep(2)

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Error: Tidak dapat mengakses kamera.")
    exit()

print("Silakan posisikan wajah Anda di tengah layar dan tekan 'SPACE' untuk memotret.")

while True:
    ret, frame = cap.read()
    if not ret:
        print("Gagal membaca frame.")
        break
        
    frame = cv2.flip(frame, 1)
    
    # Gambar panduan kotak
    h, w, _ = frame.shape
    cv2.rectangle(frame, (w//2 - 150, h//2 - 150), (w//2 + 150, h//2 + 150), (0, 255, 0), 2)
    cv2.putText(frame, "Tekan SPASI untuk Foto, atau ESC untuk Batal", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    
    cv2.imshow("Registrasi Face ID", frame)
    
    key = cv2.waitKey(1) & 0xFF
    if key == 32:  # SPASI
        os.makedirs('faces', exist_ok=True)
        filepath = os.path.join('faces', f'{nama_user}.jpg')
        cv2.imwrite(filepath, frame)
        print(f"✅ Berhasil! Foto wajah Anda telah disimpan di '{filepath}'.")
        break
    elif key == 27:  # ESC
        print("Dibatalkan.")
        break

cap.release()
cv2.destroyAllWindows()
