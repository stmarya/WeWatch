import os
import cv2
import face_recognition
import logging
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

class AIModelManager:
    def __init__(self):
        logging.info("Initializing MediaPipe Models...")
        try:
            self.face_detector = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path='face_landmarker.task'),
                output_face_blendshapes=True, output_facial_transformation_matrixes=True, num_faces=1))
            
            self.hands_detector = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path='hand_landmarker.task'), num_hands=2))
            
            self.pose_detector = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path='pose_landmarker.task')))
            
            self.segmenter = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
                base_options=python.BaseOptions(model_asset_path='selfie_segmenter.tflite'), output_category_mask=True))
                
            self.object_detector = vision.ObjectDetector.create_from_options(vision.ObjectDetectorOptions(
                base_options=python.BaseOptions(model_asset_path='efficientdet_lite0.tflite'), max_results=5, score_threshold=0.3))
                
            logging.info("All MediaPipe Models Loaded Successfully.")
        except Exception as e:
            logging.error(f"Failed to load MediaPipe models: {e}")

        # Identitas Face Recognition
        self.known_face_encodings = []
        self.known_face_names = []
        os.makedirs('faces', exist_ok=True)
        for filename in os.listdir('faces'):
            if filename.endswith('.jpg') or filename.endswith('.png'):
                try:
                    name = os.path.splitext(filename)[0]
                    img_ref = face_recognition.load_image_file(os.path.join('faces', filename))
                    encodings = face_recognition.face_encodings(img_ref)
                    if encodings:
                        self.known_face_encodings.append(encodings[0])
                        self.known_face_names.append(name)
                        logging.info(f"Face Identity '{name}' loaded.")
                    else:
                        logging.warning(f"No face found in {filename}.")
                except Exception as e:
                    logging.warning(f"Could not load {filename}: {e}")
                    
        # Fallback for old wajah_saya.jpg
        if os.path.exists('wajah_saya.jpg') and "wajah_saya" not in self.known_face_names:
            try:
                img_ref = face_recognition.load_image_file('wajah_saya.jpg')
                self.known_face_encodings.append(face_recognition.face_encodings(img_ref)[0])
                self.known_face_names.append("Altar (Legacy)")
                logging.info("Face Identity 'wajah_saya.jpg' loaded.")
            except Exception as e:
                pass
                
        # Asset Kacamata, Kumis, Topi
        try: self.kacamata_img = cv2.imread('kacamata.png', cv2.IMREAD_UNCHANGED)
        except: self.kacamata_img = None
        
        try: self.mustache_img = cv2.imread('assets/mustache.png', cv2.IMREAD_UNCHANGED)
        except: self.mustache_img = None
        
        try: self.tophat_img = cv2.imread('assets/tophat.png', cv2.IMREAD_UNCHANGED)
        except: self.tophat_img = None
