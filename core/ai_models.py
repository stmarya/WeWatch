import os
import cv2
import face_recognition
import logging
from pathlib import Path
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

class AIModelManager:
    def __init__(self):
        logging.info("Initializing MediaPipe Models...")
        self.face_detector = None
        self.hands_detector = None
        self.pose_detector = None
        self.segmenter = None
        self.object_detector = None
        self.kacamata_img = None
        self.mustache_img = None
        self.tophat_img = None
        self.base_dir = Path(__file__).resolve().parent.parent
        try:
            self.face_detector = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=str(self.base_dir / 'face_landmarker.task')),
                output_face_blendshapes=True, output_facial_transformation_matrixes=True, num_faces=1))
            
            self.hands_detector = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=str(self.base_dir / 'hand_landmarker.task')), num_hands=2))
            
            self.pose_detector = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=str(self.base_dir / 'pose_landmarker.task'))))
            
            self.segmenter = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
                base_options=python.BaseOptions(model_asset_path=str(self.base_dir / 'selfie_segmenter.tflite')), output_category_mask=True))
                
            self.object_detector = vision.ObjectDetector.create_from_options(vision.ObjectDetectorOptions(
                base_options=python.BaseOptions(model_asset_path=str(self.base_dir / 'efficientdet_lite0.tflite')), max_results=5, score_threshold=0.3))
                
            logging.info("All MediaPipe Models Loaded Successfully.")
        except Exception as e:
            logging.error(f"Failed to load MediaPipe models: {e}")

        # Identitas Face Recognition
        self.known_face_encodings = []
        self.known_face_names = []
        faces_dir = self.base_dir / 'faces'
        faces_dir.mkdir(exist_ok=True)
        for filename in os.listdir(faces_dir):
            if filename.endswith('.jpg') or filename.endswith('.png'):
                try:
                    # Allow optional multi-sample enrollment files such as
                    # `alice__left.jpg` while keeping existing `alice.jpg`
                    # registrations compatible.
                    name = os.path.splitext(filename)[0].split('__', 1)[0]
                    img_ref = face_recognition.load_image_file(faces_dir / filename)
                    encodings = face_recognition.face_encodings(img_ref, num_jitters=2)
                    if encodings:
                        self.known_face_encodings.append(encodings[0])
                        self.known_face_names.append(name)
                        logging.info(f"Face Identity '{name}' loaded.")
                    else:
                        logging.warning(f"No face found in {filename}.")
                except Exception as e:
                    logging.warning(f"Could not load {filename}: {e}")
                    
        # Fallback for old wajah_saya.jpg
        legacy_face = self.base_dir / 'wajah_saya.jpg'
        if legacy_face.exists() and "wajah_saya" not in self.known_face_names:
            try:
                img_ref = face_recognition.load_image_file(legacy_face)
                encodings = face_recognition.face_encodings(img_ref)
                if not encodings:
                    raise ValueError("no face found")
                self.known_face_encodings.append(encodings[0])
                self.known_face_names.append("Altar (Legacy)")
                logging.info("Face Identity 'wajah_saya.jpg' loaded.")
            except Exception as e:
                logging.warning("Could not load legacy face %s: %s", legacy_face, e)
                
        # Asset Kacamata, Kumis, Topi
        try:
            self.kacamata_img = cv2.imread(
                str(self.base_dir / 'kacamata.png'), cv2.IMREAD_UNCHANGED
            )
        except Exception as exc:
            logging.warning("Could not load kacamata asset: %s", exc)
            self.kacamata_img = None
        
        try:
            self.mustache_img = cv2.imread(
                str(self.base_dir / 'assets/mustache.png'), cv2.IMREAD_UNCHANGED
            )
        except Exception as exc:
            logging.warning("Could not load mustache asset: %s", exc)
            self.mustache_img = None
        
        try:
            self.tophat_img = cv2.imread(
                str(self.base_dir / 'assets/tophat.png'), cv2.IMREAD_UNCHANGED
            )
        except Exception as exc:
            logging.warning("Could not load tophat asset: %s", exc)
            self.tophat_img = None
