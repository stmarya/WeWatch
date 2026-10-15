"""Compatibility for legacy face-recognition-models without pkg_resources.

The 0.3.0 package only exposes four resource paths, but imports the removed
setuptools pkg_resources API. Use installed distribution paths instead of
retaining a vulnerable setuptools version. No model download or code execution.
"""
from importlib import import_module, metadata
from pathlib import Path
import sys
import types

MODEL_FILES = {
    'pose_predictor_model_location': 'shape_predictor_68_face_landmarks.dat',
    'pose_predictor_five_point_model_location': 'shape_predictor_5_face_landmarks.dat',
    'face_recognition_model_location': 'dlib_face_recognition_resnet_model_v1.dat',
    'cnn_face_detector_model_location': 'mmod_human_face_detector.dat',
}


def legacy_models_adapter(distribution):
    """Adapt only the known legacy package; refuse missing model assets."""
    if distribution.version != '0.3.0':
        raise RuntimeError('Unsupported legacy face-recognition-models version')
    module = types.ModuleType('face_recognition_models')
    for function, filename in MODEL_FILES.items():
        path = Path(distribution.locate_file('face_recognition_models/models/' + filename))
        if not path.is_file():
            raise RuntimeError('Installed face model asset is missing: ' + filename)
        setattr(module, function, lambda resource=str(path): resource)
    return module


def load_face_recognition():
    try:
        return import_module('face_recognition')
    except ModuleNotFoundError as exc:
        if exc.name != 'pkg_resources':
            raise
        # Failed package imports are removed by Python before this fallback.
        distribution = metadata.distribution('face-recognition-models')
        sys.modules['face_recognition_models'] = legacy_models_adapter(distribution)
        return import_module('face_recognition')


face_recognition = load_face_recognition()
