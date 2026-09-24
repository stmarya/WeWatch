import os
import glob
import sqlite3
import time
import logging
from flask import Flask, render_template, Response, request, jsonify
from dotenv import load_dotenv

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("Starting The Ultimate Watcher Server...")

# Load Env
load_dotenv()

from camera import AICamera, FEATURES, STATUS
from services.jarvis import start_jarvis

app = Flask(__name__)

GALLERY_FOLDER = os.path.join('static', 'gallery')
os.makedirs(GALLERY_FOLDER, exist_ok=True)

from services.database import init_attendance_db
init_attendance_db()

# Initialize Camera with AI processing in background
camera = AICamera(FEATURES, STATUS)

# Mulai pendengar Jarvis di background
start_jarvis(camera)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "short_name": "Google Meet",
        "name": "Google Meet Admin",
        "icons": [
            {
                "src": "https://fonts.gstatic.com/s/i/productlogos/meet_2020q4/v6/web-512dp/logo_meet_2020q4_color_2x_web_512dp.png",
                "type": "image/png",
                "sizes": "512x512"
            }
        ],
        "start_url": "/",
        "background_color": "#202124",
        "theme_color": "#202124",
        "display": "standalone",
        "orientation": "any"
    })

@app.route('/gallery')
def gallery():
    images = glob.glob(os.path.join(GALLERY_FOLDER, '*.jpg'))
    images.sort(key=os.path.getmtime, reverse=True)
    image_urls = [os.path.basename(img) for img in images]
    return render_template('gallery.html', images=image_urls)

@app.route('/toggle', methods=['POST'])
def toggle():
    data = request.json
    feature = data.get('feature')
    state = data.get('state')
    if feature in FEATURES:
        FEATURES[feature] = state
        logging.info(f"Feature {feature} set to {state}")
    return jsonify(success=True)

@app.route('/snap_face', methods=['POST'])
def snap_face():
    name = request.json.get('name', 'user_default').strip()
    if not name:
        name = 'user_default'
    
    if camera.frame_rgb is not None:
        import cv2
        os.makedirs('faces', exist_ok=True)
        filepath = os.path.join('faces', f'{name}.jpg')
        bgr_frame = cv2.cvtColor(camera.frame_rgb, cv2.COLOR_RGB2BGR)
        cv2.imwrite(filepath, bgr_frame)
        
        import face_recognition
        try:
            img_ref = face_recognition.load_image_file(filepath)
            encodings = face_recognition.face_encodings(img_ref)
            if encodings:
                camera.ai.known_face_encodings.append(encodings[0])
                camera.ai.known_face_names.append(name)
                return jsonify(success=True, message=f"Wajah '{name}' berhasil didaftarkan! AI sekarang mengenali Anda.")
            else:
                return jsonify(success=False, message="Wajah tidak terdeteksi pada foto. Silakan coba lagi.")
        except Exception as e:
            return jsonify(success=False, message=str(e))
    return jsonify(success=False, message="Kamera belum siap.")

@app.route('/take_snapshot', methods=['POST'])
def take_snapshot():
    if camera.frame_rgb is not None:
        try:
            import cv2
            filename = f"snapshot_{int(time.time())}.jpg"
            filepath = os.path.join(GALLERY_FOLDER, filename)
            bgr_frame = cv2.cvtColor(camera.frame_rgb, cv2.COLOR_RGB2BGR)
            cv2.imwrite(filepath, bgr_frame)
            return jsonify(success=True, filename=filename, url=f"/static/gallery/{filename}", message="Foto berhasil disimpan ke galeri!")
        except Exception as e:
            return jsonify(success=False, message=str(e))
    return jsonify(success=False, message="Kamera belum siap.")

@app.route('/status_data')
def status_data():
    return jsonify({'status': STATUS, 'features': FEATURES})

@app.route('/mood_data')
def mood_data():
    try:
        conn = sqlite3.connect('mood.db')
        c = conn.cursor()
        c.execute("SELECT emosi, COUNT(*) FROM mood GROUP BY emosi")
        rows = c.fetchall()
        conn.close()
        
        data = {'Senyum': 0, 'Netral': 0, 'Terkejut': 0, 'MataTertutup': 0}
        for row in rows:
            if row[0] == "Senyum": data['Senyum'] = row[1]
            elif row[0] == "Netral": data['Netral'] = row[1]
            elif row[0] == "Terkejut": data['Terkejut'] = row[1]
            elif row[0] == "Mata Tertutup": data['MataTertutup'] = row[1]
        return jsonify(data)
    except Exception as e:
        logging.error(f"Failed to fetch mood data: {e}")
        return jsonify({'Senyum': 0, 'Netral': 0, 'Terkejut': 0, 'MataTertutup': 0})

def gen_frames():
    while True:
        frame = camera.get_frame()
        if frame is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.025)  # Ultra-smooth ~40 FPS target
        else:
            time.sleep(0.005)

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

def run_web_server():
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    logging.info("Membuka Server di http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)

if __name__ == '__main__':
    run_web_server()
