import numpy as np
import math

def calculate_angle(a, b, c):
    # Menghitung sudut antara 3 titik (misal: bahu, siku, pergelangan)
    a = np.array(a)
    b = np.array(b)
    c = np.array(c)
    
    radians = np.arctan2(c[1] - b[1], c[0] - b[0]) - np.arctan2(a[1] - b[1], a[0] - b[0])
    angle = np.abs(radians * 180.0 / np.pi)
    
    if angle > 180.0:
        angle = 360 - angle
        
    return angle


def is_thumbs_up(hl):
    # Jempol ke atas, jari lain mengepal ke bawah
    return (hl[4].y < hl[5].y and hl[4].y < hl[17].y and hl[8].y > hl[5].y and hl[12].y > hl[9].y)

def is_i_love_you(hl):
    thumb_ext = hl[4].y < hl[3].y
    index_ext = hl[8].y < hl[6].y
    middle_folded = hl[12].y > hl[10].y
    ring_folded = hl[16].y > hl[14].y
    pinky_ext = hl[20].y < hl[18].y
    return thumb_ext and index_ext and middle_folded and ring_folded and pinky_ext

def is_hello(hl):
    index_ext = hl[8].y < hl[6].y
    middle_ext = hl[12].y < hl[10].y
    ring_ext = hl[16].y < hl[14].y
    pinky_ext = hl[20].y < hl[18].y
    return index_ext and middle_ext and ring_ext and pinky_ext

def is_ok(hl):
    dist = math.hypot(hl[4].x - hl[8].x, hl[4].y - hl[8].y)
    middle_ext = hl[12].y < hl[10].y
    ring_ext = hl[16].y < hl[14].y
    pinky_ext = hl[20].y < hl[18].y
    return dist < 0.05 and middle_ext and ring_ext and pinky_ext

def get_gaze_direction(iris_center, eye_left, eye_right):
    eye_width = math.hypot(eye_right.x - eye_left.x, eye_right.y - eye_left.y)
    if eye_width == 0: 
        return "TENGAH"
        
    iris_dist_to_left = math.hypot(iris_center.x - eye_left.x, iris_center.y - eye_left.y)
    ratio = iris_dist_to_left / eye_width
    
    if ratio <= 0.42:
        return "KIRI"
    elif ratio >= 0.58:
        return "KANAN"
    else:
        return "TENGAH"

def is_v_sign(hl):
    # Jari telunjuk dan tengah ke atas, jari manis dan kelingking ke bawah
    return (hl[8].y < hl[5].y and hl[12].y < hl[9].y and hl[16].y > hl[13].y and hl[20].y > hl[17].y)

def calculate_bpm(buffer, fps=15, timestamps=None):
    """Experimental pulse estimate, NOT medical measurement; 0 = insufficient data.

    Reject low-quality/flat signals, gaps and impossible sampling instead of
    clamping noise to a plausible-looking 50–180 BPM.
    """
    values = np.asarray(buffer, dtype=float)
    if len(values) < 60 or not np.all(np.isfinite(values)):
        return 0
    times = np.asarray(timestamps, dtype=float) if timestamps is not None else np.arange(len(values)) / fps
    if len(times) != len(values) or not np.all(np.isfinite(times)):
        return 0
    delta = np.diff(times)
    if np.any(delta <= 0) or np.max(delta) > 0.5 or times[-1] - times[0] < 10:
        return 0
    rate = (len(times) - 1) / (times[-1] - times[0])
    if rate < 6:
        return 0
    uniform = np.linspace(times[0], times[-1], len(times))
    signal = np.interp(uniform, times, values)
    # Remove mean and linear lighting drift before spectral estimation.
    signal -= np.polyval(np.polyfit(uniform - uniform[0], signal, 1), uniform - uniform[0])
    if np.std(signal) < 0.05:
        return 0
    power = np.abs(np.fft.rfft(signal * np.hanning(len(signal)))) ** 2
    frequencies = np.fft.rfftfreq(len(signal), d=1 / rate)
    band = (frequencies >= 0.75) & (frequencies <= 3.0)
    band_power = power[band]
    if not len(band_power) or np.sum(band_power) <= 0:
        return 0
    peak = int(np.argmax(band_power))
    if band_power[peak] / np.sum(band_power) < 0.35:
        return 0
    return int(round(frequencies[band][peak] * 60))

def overlay_transparent(bg, overlay, x, y):
    # Menempelkan gambar PNG (Kacamata) dengan transparansi (Alpha channel)
    bg_h, bg_w, _ = bg.shape
    if x >= bg_w or y >= bg_h: return bg
    h, w = overlay.shape[0], overlay.shape[1]
    
    if x + w > bg_w: w, overlay = bg_w - x, overlay[:, :w]
    if y + h > bg_h: h, overlay = bg_h - y, overlay[:h]
    if x < 0: overlay, w, x = overlay[:, -x:], w + x, 0
    if y < 0: overlay, h, y = overlay[-y:, :], h + y, 0
    
    if w <= 0 or h <= 0: return bg
    
    mask = overlay[..., 3:] / 255.0
    bg[y:y+h, x:x+w] = (1.0 - mask) * bg[y:y+h, x:x+w] + mask * overlay[..., :3]
    return bg
