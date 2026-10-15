"""Dependency-free inference policy, testable without a camera or models."""

import math

MODEL_REQUIREMENTS = {
    'kantuk': ('face_detector',), 'kacamata': ('face_detector', 'kacamata_img'),
    'hands': ('hands_detector',), 'bosskey': ('hands_detector',),
    'blur': ('segmenter',), 'postur': ('pose_detector',), 'trainer': ('pose_detector',),
    'object': ('object_detector',), 'produktivitas': ('face_detector', 'pose_detector', 'object_detector'),
    'sign_language': ('hands_detector',), 'gaze_tracking': ('face_detector',),
    'liveness': ('face_detector',), 'virtual_keyboard': ('hands_detector',),
    'tryon_kumis': ('face_detector', 'mustache_img'), 'tryon_topi': ('face_detector', 'tophat_img'),
}


def select_identity(names, distances, threshold=0.54, margin=0.035):
    """Compare minimum distances per ID, not two enrollment samples of one ID."""
    by_identity = {}
    for name, distance in zip(names, distances):
        distance = float(distance)
        if not math.isfinite(distance) or distance < 0:
            continue
        by_identity[name] = min(distance, by_identity.get(name, float('inf')))
    ranked = sorted(by_identity.items(), key=lambda item: item[1])
    if not ranked or ranked[0][1] > threshold:
        return 'Tidak Dikenal'
    if len(ranked) > 1 and ranked[1][1] - ranked[0][1] < margin:
        return 'Tidak Dikenal'
    return ranked[0][0]
