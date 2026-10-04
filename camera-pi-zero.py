#!/usr/bin/env python3
"""
Raspberry Pi HQ Camera Script — HIGHLY OPTIMIZED FOR PI ZERO
- Sensor:  Official Raspberry Pi HQ Camera (IMX477)
- Display: 3.5" GPIO touchscreen, 480x320
- Shutter: GPIO26 momentary button (hold 2s = shutter-set mode, short = capture/cycle)
- Film profiles: tap the on-screen FILM button to cycle through profiles
"""

import os
import json
import time
import threading
import traceback
from datetime import datetime

import cv2
import numpy as np
import simplejpeg
from gpiozero import Button
from picamera2 import Picamera2

# ------------------------------------------------------------
#  Configuration
# ------------------------------------------------------------
PICTURES_DIR = "/home/pi/Pictures"

SCREEN_W, SCREEN_H = 480, 320
BAR_H      = 40
EDGE_INSET = 10
CONTROL_GAP = 5
FILM_BTN_W = 200
FILM_BTN_H = 48
PHOTO_BTN_W = 170
PHOTO_BTN_H = 48
PEAK_BTN_W = PHOTO_BTN_W
SHUTTER_BTN_SIZE = 72
SETTINGS_PATH = os.path.expanduser("~/.config/rpi-film-camera/settings.json")
PROFILE_HOLD_SECS = 0.8

# Non-standard previews are deliberately approximate on the single-core Zero.
# Work at half the display dimensions, then upscale once for display.
PROFILE_W, PROFILE_H = 240, 160

PEAK_THRESHOLD = 45
PEAK_W, PEAK_H = 120, 80
UI_EVERY       = 4
PERF_LOG_SECS  = 5.0
JPEG_QUALITY   = 92

EV_OPTIONS = [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0]
current_ev_idx = 4

AWB_MODES = [("Auto", 0), ("Daylight", 5), ("Cloudy", 6), ("Tungsten", 2), ("Fluorescent", 3)]
current_awb_idx = 0

zoom_levels      = [1.0, 2.0, 4.0]
current_zoom_idx = 0
zoom_center      = (0.5, 0.5)

sleep_mode       = False
press_start_time = 0.0
image_count      = 0
focus_peaking_enabled = False
capture_busy = False

PHOTO_MODES = [
    ("12MP", (4056, 3040)),
    ("3MP",  (2028, 1520)),
]
current_photo_idx = 0

os.system("unclutter &")
os.makedirs(PICTURES_DIR, exist_ok=True)

btn_bounds       = {"bx1": 0, "bx2": FILM_BTN_W, "by1": 0, "by2": FILM_BTN_H}
btn_bounds_ev    = {"bx1": 0, "bx2": 0, "by1": 0, "by2": 0}
btn_bounds_awb   = {"bx1": 0, "bx2": 0, "by1": 0, "by2": 0}
btn_bounds_pm    = {"bx1": 0, "bx2": 0, "by1": 0, "by2": 0}
btn_bounds_meter = {"bx1": 0, "bx2": 0, "by1": 0, "by2": 0}
btn_bounds_photo = {"bx1": 0, "bx2": 0, "by1": 0, "by2": 0}
btn_bounds_peak  = {"bx1": 0, "bx2": 0, "by1": 0, "by2": 0}
btn_bounds_shutter = {"bx1": 0, "bx2": 0, "by1": 0, "by2": 0}
btn_bounds_sleep = {"bx1": 0, "bx2": 0, "by1": 0, "by2": 0}

# ============================================================
#  PRECOMPUTED ASSETS (Built once at startup)
# ============================================================

def _lut_from_curve(pts):
    xs = np.array([p[0] for p in pts], dtype=np.float32)
    ys = np.array([p[1] for p in pts], dtype=np.float32)
    return np.clip(np.interp(np.arange(256), xs, ys), 0, 255).astype(np.uint8)

# --- Channel LUTs ---
_LUT_CC_B = _lut_from_curve([(0,25),(64,80),(128,132),(192,188),(255,242)])
_LUT_CC_G = _lut_from_curve([(0,18),(64,72),(128,126),(192,184),(255,238)])
_LUT_CC_R = _lut_from_curve([(0,20),(64,75),(128,128),(192,185),(255,240)])

_LUT_KP_B = _lut_from_curve([(0,12),(64,68),(128,118),(192,172),(255,220)])
_LUT_KP_G = _lut_from_curve([(0, 8),(64,74),(128,130),(192,192),(255,248)])
_LUT_KP_R = _lut_from_curve([(0,10),(64,80),(128,138),(192,200),(255,255)])

_LUT_FV_B = _lut_from_curve([(0,0),(64,66),(128,140),(192,208),(255,255)])
_LUT_FV_G = _lut_from_curve([(0,0),(64,62),(128,135),(192,205),(255,255)])
_LUT_FV_R = _lut_from_curve([(0,0),(64,60),(128,130),(192,200),(255,255)])

_LUT_FA_B = _lut_from_curve([(0,8),(64,70),(128,126),(192,188),(255,245)])
_LUT_FA_G = _lut_from_curve([(0,4),(64,70),(128,130),(192,194),(255,250)])
_LUT_FA_R = _lut_from_curve([(0,5),(64,72),(128,132),(192,196),(255,252)])

_LUT_IB   = _lut_from_curve([(0,0),(60,50),(128,128),(190,210),(255,255)])

_LUT_KG_B = _lut_from_curve([(0,20),(64,60),(128,110),(192,162),(255,210)])
_LUT_KG_G = _lut_from_curve([(0,10),(64,76),(128,132),(192,194),(255,248)])
_LUT_KG_R = _lut_from_curve([(0,15),(64,85),(128,142),(192,205),(255,255)])

# Small midtone shifts keep whites and skin from becoming orange.
_LUT_WN_B = _lut_from_curve([(0,0),(64,62),(128,124),(192,190),(255,255)])
_LUT_WN_G = _lut_from_curve([(0,0),(64,64),(128,128),(192,192),(255,255)])
_LUT_WN_R = _lut_from_curve([(0,0),(64,66),(128,132),(192,194),(255,255)])
_LUT_GD_B = _lut_from_curve([(0,0),(64,61),(128,123),(192,187),(255,255)])
_LUT_GD_G = _lut_from_curve([(0,0),(64,65),(128,129),(192,193),(255,255)])
_LUT_GD_R = _lut_from_curve([(0,0),(64,67),(128,134),(192,197),(255,255)])
_LUT_SN_B = _lut_from_curve([(0,6),(64,66),(128,124),(192,187),(255,249)])
_LUT_SN_G = _lut_from_curve([(0,6),(64,67),(128,128),(192,190),(255,250)])
_LUT_SN_R = _lut_from_curve([(0,7),(64,69),(128,133),(192,195),(255,252)])

def _make_channel_lut(lb, lg, lr):
    """Build the 3-channel LUT layout accepted by cv2.LUT."""
    return np.stack((lb, lg, lr), axis=1).reshape(256, 1, 3)

_LUT_CC = _make_channel_lut(_LUT_CC_B, _LUT_CC_G, _LUT_CC_R)
_LUT_KP = _make_channel_lut(_LUT_KP_B, _LUT_KP_G, _LUT_KP_R)
_LUT_FV = _make_channel_lut(_LUT_FV_B, _LUT_FV_G, _LUT_FV_R)
_LUT_FA = _make_channel_lut(_LUT_FA_B, _LUT_FA_G, _LUT_FA_R)
_LUT_KG = _make_channel_lut(_LUT_KG_B, _LUT_KG_G, _LUT_KG_R)
_LUT_WN = _make_channel_lut(_LUT_WN_B, _LUT_WN_G, _LUT_WN_R)
_LUT_GD = _make_channel_lut(_LUT_GD_B, _LUT_GD_G, _LUT_GD_R)
_LUT_SN = _make_channel_lut(_LUT_SN_B, _LUT_SN_G, _LUT_SN_R)

_LUT_SAT_072 = np.clip(np.arange(256) * 0.72, 0, 255).astype(np.uint8)
_LUT_SAT_085 = np.clip(np.arange(256) * 0.85, 0, 255).astype(np.uint8)
_LUT_SAT_090 = np.clip(np.arange(256) * 0.90, 0, 255).astype(np.uint8)
_LUT_SAT_095 = np.clip(np.arange(256) * 0.95, 0, 255).astype(np.uint8)
_LUT_SAT_145 = np.clip(np.arange(256) * 1.45, 0, 255).astype(np.uint8)
_LUT_HUE_MINUS_3 = ((np.arange(256, dtype=np.int16) - 3) % 180).astype(np.uint8)

# --- Vignette masks ---
def _make_vignette_mask(w, h, strength):
    Y, X     = np.ogrid[:h, :w]
    dist     = np.sqrt(((X - w/2)/(w/2))**2 + ((Y - h/2)/(h/2))**2)
    mask     = 1.0 - np.clip(dist * strength, 0, 1)
    mask_3ch = np.stack([mask, mask, mask], axis=-1)
    return (mask_3ch * 255).astype(np.uint8)

_VIG_MASK_PREVIEW_KP = _make_vignette_mask(PROFILE_W, PROFILE_H, 0.25)
_VIG_MASK_PREVIEW_KG = _make_vignette_mask(PROFILE_W, PROFILE_H, 0.30)

# --- Grain buffers (add/sub split avoids float32) ---
_noise_kg = np.random.normal(0, 4, (PROFILE_H, PROFILE_W, 3))
_GRAIN_KG_ADD = np.clip( _noise_kg, 0, 255).astype(np.uint8)
_GRAIN_KG_SUB = np.clip(-_noise_kg, 0, 255).astype(np.uint8)

_noise_ib = np.random.normal(0, 5, (PROFILE_H, PROFILE_W, 3))
_GRAIN_IB_ADD = np.clip( _noise_ib, 0, 255).astype(np.uint8)
_GRAIN_IB_SUB = np.clip(-_noise_ib, 0, 255).astype(np.uint8)
del _noise_kg, _noise_ib

# --- Static canvas buffer ---
_canvas = np.zeros((SCREEN_H, SCREEN_W, 3), dtype=np.uint8)

# --- Text block cache ---
_tb_cache = {}
_control_cache = {}

# ============================================================
#  FAST HELPERS
# ============================================================

def _apply_channel_lut(img, lut):
    return cv2.LUT(img, lut)

def _sat_fast(img, scale):
    """Saturation via grayscale blend — avoids HSV round-trip."""
    gray    = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray_3ch = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return cv2.addWeighted(img, scale, gray_3ch, 1.0 - scale, 0)

def _vignette_fast(img, mask_u8):
    h, w = img.shape[:2]
    mh, mw = mask_u8.shape[:2]
    # Clamp mask to actual image size (handles zoom crop size mismatches)
    m = mask_u8[:h, :w] if (h <= mh and w <= mw) else cv2.resize(mask_u8, (w, h), interpolation=cv2.INTER_NEAREST)
    return cv2.multiply(img, m, scale=1.0/255.0)

def _vignette_still(img, strength, rows_per_chunk=128):
    """Apply a vignette in-place without full-resolution float temporaries."""
    h, w = img.shape[:2]
    x_norm_sq = ((np.arange(w, dtype=np.float32) - w / 2) / (w / 2)) ** 2
    for y1 in range(0, h, rows_per_chunk):
        y2 = min(h, y1 + rows_per_chunk)
        y_norm_sq = ((np.arange(y1, y2, dtype=np.float32) - h / 2) / (h / 2)) ** 2
        dist = np.sqrt(y_norm_sq[:, np.newaxis] + x_norm_sq[np.newaxis, :])
        mask = ((1.0 - np.clip(dist * strength, 0, 1)) * 255).astype(np.uint8)
        mask_3ch = cv2.merge((mask, mask, mask))
        cv2.multiply(img[y1:y2], mask_3ch, dst=img[y1:y2], scale=1.0 / 255.0)
    return img

def _grain_fast(img, g_add, g_sub):
    h, w = img.shape[:2]
    gh, gw = g_add.shape[:2]
    if h != gh or w != gw:
        return img  # size guard during zoom
    return cv2.subtract(cv2.add(img, g_add), g_sub)

def _grain_still(img, amount, rows_per_chunk=128):
    """Generate signed grain in OpenCV, one bounded stripe at a time."""
    h, w = img.shape[:2]
    noise = np.empty((rows_per_chunk, w, 3), dtype=np.int16)
    for y1 in range(0, h, rows_per_chunk):
        y2 = min(h, y1 + rows_per_chunk)
        stripe = img[y1:y2]
        n = noise[:y2-y1]
        cv2.randn(n, (0, 0, 0), (amount, amount, amount))
        cv2.add(stripe, n, dst=stripe, dtype=cv2.CV_8U)
    return img

def _hsv_saturation(img, saturation_lut, hue_lut=None):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hsv[:, :, 1] = cv2.LUT(hsv[:, :, 1], saturation_lut)
    if hue_lut is not None:
        hsv[:, :, 0] = cv2.LUT(hsv[:, :, 0], hue_lut)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

def apply_pro_mist(img, threshold=190, glow_spread=15, blend=0.25):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    highlights = cv2.bitwise_and(img, img, mask=mask)
    h, w = img.shape[:2]
    small = cv2.resize(highlights, (w//4, h//4), interpolation=cv2.INTER_NEAREST)
    if glow_spread % 2 == 0: glow_spread += 1
    blurred = cv2.GaussianBlur(small, (glow_spread, glow_spread), 0)
    blurred = cv2.resize(blurred, (w, h), interpolation=cv2.INTER_NEAREST)
    return cv2.addWeighted(img, 1.0, blurred, blend, 0)

# ============================================================
#  FILM PROFILES
# ============================================================

def profile_standard(img, preview=True):
    return img

def profile_classic_chrome(img, preview=True):
    out = _apply_channel_lut(img, _LUT_CC)
    return _sat_fast(out, 0.72)

def profile_kodak_portra(img, preview=True):
    out = _apply_channel_lut(img, _LUT_KP)
    if preview:
        return _vignette_fast(_sat_fast(out, 0.85), _VIG_MASK_PREVIEW_KP)
    return _vignette_still(_sat_fast(out, 0.85), 0.25)

def profile_fuji_velvia(img, preview=True):
    out = _apply_channel_lut(img, _LUT_FV)
    return _hsv_saturation(out, _LUT_SAT_145, _LUT_HUE_MINUS_3)

def profile_fuji_astia(img, preview=True):
    out = _apply_channel_lut(img, _LUT_FA)
    return _sat_fast(out, 0.95)

def profile_ilford_bw(img, preview=True):
    pan = cv2.transform(img, np.array([[0.07, 0.72, 0.21]], dtype=np.float32))
    if pan.ndim == 3:
        pan = pan[:, :, 0]
    pan = cv2.LUT(pan, _LUT_IB)
    bgr = cv2.cvtColor(pan, cv2.COLOR_GRAY2BGR)
    if preview:
        return _grain_fast(bgr, _GRAIN_IB_ADD, _GRAIN_IB_SUB)
    return _grain_still(bgr, 5)

def profile_kodak_gold(img, preview=True):
    out = _apply_channel_lut(img, _LUT_KG)
    if preview:
        out = _sat_fast(out, 0.90)
        out = _vignette_fast(out, _VIG_MASK_PREVIEW_KG)
        return _grain_fast(out, _GRAIN_KG_ADD, _GRAIN_KG_SUB)
    out = _vignette_still(_sat_fast(out, 0.90), 0.30)
    return _grain_still(out, 4)

def profile_warm_natural(img, preview=True):
    return _apply_channel_lut(img, _LUT_WN)

def profile_golden_daylight(img, preview=True):
    return _apply_channel_lut(img, _LUT_GD)

def profile_soft_nostalgia(img, preview=True):
    return _sat_fast(_apply_channel_lut(img, _LUT_SN), 0.92)

FILM_PROFILES = [
    ("Standard",       profile_standard,       (180, 180, 180)),
    ("Classic Chrome", profile_classic_chrome,  ( 80, 180, 160)),
    ("Kodak Portra",   profile_kodak_portra,    ( 40, 140, 230)),
    ("Fuji Velvia",    profile_fuji_velvia,     ( 30, 200,  90)),
    ("Fuji Astia",     profile_fuji_astia,      (200, 160,  80)),
    ("Ilford B&W",     profile_ilford_bw,       (210, 210, 210)),
    ("Kodak Gold",     profile_kodak_gold,      (  0, 190, 230)),
    ("Warm Natural",   profile_warm_natural,    (100, 180, 230)),
    ("Golden Daylight",profile_golden_daylight, ( 60, 190, 240)),
    ("Soft Nostalgia", profile_soft_nostalgia,  (140, 170, 220)),
]
PROFILE_IDS = ["standard", "classic_chrome", "kodak_portra", "fuji_velvia",
               "fuji_astia", "ilford_bw", "kodak_gold", "warm_natural",
               "golden_daylight", "soft_nostalgia"]

def _chroma_lut(saturation=1.0, offset=0):
    values = (np.arange(256, dtype=np.float32) - 128) * saturation + 128 + offset
    return np.clip(values, 0, 255).astype(np.uint8)

# These restrained YUV adjustments approximate the warm RGB preview curves and
# let full-resolution warm photos use Picamera2's fast planar JPEG encoder.
_WARM_YUV_STYLES = {
    PROFILE_IDS.index("warm_natural"): (
        _lut_from_curve([(0,0),(64,64),(128,129),(192,193),(255,255)]),
        _chroma_lut(offset=-3), _chroma_lut(offset=2)),
    PROFILE_IDS.index("golden_daylight"): (
        _lut_from_curve([(0,0),(64,65),(128,130),(192,194),(255,255)]),
        _chroma_lut(offset=-4), _chroma_lut(offset=3)),
    PROFILE_IDS.index("soft_nostalgia"): (
        _lut_from_curve([(0,6),(64,67),(128,129),(192,191),(255,250)]),
        _chroma_lut(0.92, -3), _chroma_lut(0.92, 3)),
}

def style_yuv_planes(yuv, size, profile_idx):
    """Apply a warm style to YUV420 and return stride-aware planar views."""
    width, height = size
    y = yuv[:height, :width]
    planes = yuv.reshape((yuv.shape[0] * 2, yuv.strides[0] // 2))
    u = planes[2 * height: 2 * height + height // 2, :width // 2]
    v = planes[2 * height + height // 2:, :width // 2]
    y_lut, u_lut, v_lut = _WARM_YUV_STYLES[profile_idx]
    y[:] = cv2.LUT(y, y_lut)
    u[:] = cv2.LUT(u, u_lut)
    v[:] = cv2.LUT(v, v_lut)
    return y, u, v

def load_default_profile():
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as settings_file:
            profile_id = json.load(settings_file).get("default_profile", "standard")
        return PROFILE_IDS.index(profile_id)
    except (OSError, ValueError, AttributeError, TypeError):
        return 0

default_profile_idx = load_default_profile()
current_profile_idx = default_profile_idx

def save_default_profile():
    global default_profile_idx
    settings_dir = os.path.dirname(SETTINGS_PATH)
    tmp_path = SETTINGS_PATH + ".tmp"
    try:
        os.makedirs(settings_dir, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as settings_file:
            json.dump({"default_profile": PROFILE_IDS[current_profile_idx]}, settings_file)
            settings_file.flush()
            os.fsync(settings_file.fileno())
        os.replace(tmp_path, SETTINGS_PATH)
        default_profile_idx = current_profile_idx
        print(f"[Film Profile] Boot default: {FILM_PROFILES[default_profile_idx][0]}", flush=True)
    except OSError as error:
        print(f"[Film Profile] Could not save boot default: {error}", flush=True)

def apply_current_profile(img, preview=True):
    return FILM_PROFILES[current_profile_idx][1](img, preview=preview)

def cycle_film_profile():
    global current_profile_idx
    current_profile_idx = (current_profile_idx + 1) % len(FILM_PROFILES)
    print(f"[Film Profile] {FILM_PROFILES[current_profile_idx][0]}")

# ============================================================
#  CAMERA / CONTROLS
# ============================================================
METERING_MODES    = [("Matrix", 2), ("Center", 0), ("Spot", 1)]
current_meter_idx = 1

def cycle_metering():
    global current_meter_idx
    current_meter_idx = (current_meter_idx + 1) % len(METERING_MODES)
    name, val = METERING_MODES[current_meter_idx]
    picam2.set_controls({"AeMeteringMode": val})
    print(f"[Metering] {name}")

def cycle_ev():
    global current_ev_idx
    current_ev_idx = (current_ev_idx + 1) % len(EV_OPTIONS)
    val = EV_OPTIONS[current_ev_idx]
    picam2.set_controls({"ExposureValue": val})
    print(f"[EV] {val:+}")

def cycle_awb():
    global current_awb_idx
    current_awb_idx = (current_awb_idx + 1) % len(AWB_MODES)
    name, val = AWB_MODES[current_awb_idx]
    picam2.set_controls({"AwbMode": val})
    print(f"[AWB] {name}")

pro_mist_enabled = False
def toggle_pro_mist():
    global pro_mist_enabled
    pro_mist_enabled = not pro_mist_enabled
    print(f"[Pro-Mist] {'ON' if pro_mist_enabled else 'OFF'}")

def toggle_photo_resolution():
    global current_photo_idx
    current_photo_idx = (current_photo_idx + 1) % len(PHOTO_MODES)
    print(f"[Photo Resolution] {PHOTO_MODES[current_photo_idx][0]}")

def toggle_focus_peaking():
    global focus_peaking_enabled
    focus_peaking_enabled = not focus_peaking_enabled
    print(f"[Focus Peaking] {'ON' if focus_peaking_enabled else 'OFF'}")

def handle_focus_tap(x, y):
    global current_zoom_idx, zoom_center
    zoom_center      = (x / SCREEN_W, y / SCREEN_H)
    current_zoom_idx = (current_zoom_idx + 1) % len(zoom_levels)
    print(f"[Zoom] {zoom_levels[current_zoom_idx]}x @ {zoom_center}")

# ============================================================
#  SLEEP / WAKE
# ============================================================
_just_woke = False

def enter_sleep_mode():
    global sleep_mode
    if not sleep_mode:
        sleep_mode = True
        picam2.stop()
        print("[Sleep] Camera stopped", flush=True)

def wake_display():
    global sleep_mode
    if sleep_mode:
        picam2.start()
        sleep_mode = False
        print("[Sleep] Wake", flush=True)

def _on_pressed():
    global press_start_time, _just_woke
    press_start_time = time.time()
    if sleep_mode:
        _just_woke = True
    wake_display()

def _on_released():
    global _hold_fired, press_start_time, _just_woke
    if _just_woke:
        _just_woke = False
        return
    press_duration = time.time() - press_start_time
    if press_duration >= 10.0:
        return
    if press_duration > 5:
        global shutter_set_mode
        shutter_set_mode = False
        _hold_fired = False
        enter_sleep_mode()
        return
    if _hold_fired:
        _hold_fired = False
        return
    if shutter_set_mode:
        _cycle_shutter()
    else:
        request_capture()

# ============================================================
#  TOUCHSCREEN
# ============================================================
_touch_lock    = threading.Lock()
_last_tap_time = 0.0
_film_press_time = None
_film_press_pos = None

def _inside(bounds, x, y):
    return bounds["bx1"] <= x < bounds["bx2"] and bounds["by1"] <= y < bounds["by2"]

def request_capture():
    if not capture_busy and not sleep_mode:
        shoot_event.set()

def _on_mouse(event, x, y, flags, param):
    global _last_tap_time, _film_press_time, _film_press_pos
    if sleep_mode:
        if event == cv2.EVENT_LBUTTONDOWN:
            wake_display()
        return
    if capture_busy:
        return
    now = time.monotonic()
    if event == cv2.EVENT_LBUTTONUP and _film_press_time is not None:
        held = now - _film_press_time
        origin = _film_press_pos
        _film_press_time = _film_press_pos = None
        if origin and abs(x-origin[0]) <= 20 and abs(y-origin[1]) <= 20:
            if held >= PROFILE_HOLD_SECS:
                save_default_profile()
            else:
                cycle_film_profile()
        return
    if event != cv2.EVENT_LBUTTONDOWN:
        return
    if _inside(btn_bounds, x, y):
        _film_press_time = now
        _film_press_pos = (x, y)
        return
    with _touch_lock:
        if now - _last_tap_time < 0.35:
            return
        _last_tap_time = now
    if _inside(btn_bounds_photo, x, y):
        toggle_photo_resolution()
    elif _inside(btn_bounds_peak, x, y):
        toggle_focus_peaking()
    elif _inside(btn_bounds_shutter, x, y):
        request_capture()
    elif _inside(btn_bounds_sleep, x, y):
        enter_sleep_mode()
    elif _inside(btn_bounds_pm, x, y):
        toggle_pro_mist()
    elif _inside(btn_bounds_meter, x, y):
        cycle_metering()
    elif _inside(btn_bounds_ev, x, y):
        cycle_ev()
    elif _inside(btn_bounds_awb, x, y):
        cycle_awb()
    else:
        handle_focus_tap(x, y)

# ============================================================
#  DRAWING HELPERS
# ============================================================
def ensure_channels(img, ch):
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR if ch == 3 else cv2.COLOR_GRAY2BGRA)
    if img.shape[2] == ch: return img
    if img.shape[2] == 3 and ch == 4: return cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    if img.shape[2] == 4 and ch == 3: return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img

def blit_add(dst, src, x, y):
    dh, dw = dst.shape[:2]; sh, sw = src.shape[:2]
    if sw <= 0 or sh <= 0: return
    x1=max(0,x); y1=max(0,y); x2=min(dw,x+sw); y2=min(dh,y+sh)
    if x1>=x2 or y1>=y2: return
    roi   = dst[y1:y2, x1:x2]
    src_c = src[y1-y:y2-y, x1-x:x2-x]
    ch    = roi.shape[2] if roi.ndim == 3 else 3
    cv2.add(ensure_channels(roi, ch), ensure_channels(src_c, ch), dst=roi)
    dst[y1:y2, x1:x2] = roi

def format_shutter(us):
    return f"1/{int(round(1e6/us))}s" if us and us > 0 else "Auto"

# ============================================================
#  FOCUS PEAKING — detect on the current unstyled frame
# ============================================================
def make_focus_peaking_mask(frame_bgr):
    small = cv2.resize(frame_bgr, (PEAK_W, PEAK_H), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.convertScaleAbs(cv2.Laplacian(blur, cv2.CV_16S, ksize=3))
    _, mask = cv2.threshold(edges, PEAK_THRESHOLD, 255, cv2.THRESH_BINARY)
    _, light = cv2.threshold(gray, 24, 255, cv2.THRESH_BINARY)
    cv2.bitwise_and(mask, light, dst=mask)
    return cv2.resize(mask, (SCREEN_W, SCREEN_H), interpolation=cv2.INTER_NEAREST)

def apply_focus_peaking_mask(frame_bgr, mask):
    """Add visible magenta to sharp edges with OpenCV's masked C operation."""
    cv2.add(frame_bgr, (115, 0, 115, 0), dst=frame_bgr, mask=mask)
    return frame_bgr

# ============================================================
#  HISTOGRAM — fully vectorised
# ============================================================
_HIST_W = 128

def draw_histogram(gray, height=BAR_H, width=_HIST_W):
    hist  = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
    bsz   = 256 // width
    comp  = hist[:bsz*width].reshape(width, bsz).mean(axis=1)
    dmax  = max(comp.max(), 50.0)
    scale = (height - 4) / dmax
    bars  = np.minimum((comp * scale).astype(np.int32), height - 4)
    img   = np.zeros((height, width, 3), dtype=np.uint8)
    Y     = np.arange(height).reshape(height, 1)
    img[Y >= (height - 1 - bars).reshape(1, width)] = [200, 200, 200]
    return img

# ============================================================
#  TEXT BLOCK — cached
# ============================================================
def make_text_block(lines, font_scale=0.42, thickness=1, max_h=BAR_H-6):
    key = "|".join(lines)
    if key in _tb_cache:
        return _tb_cache[key]
    font   = cv2.FONT_HERSHEY_SIMPLEX
    sizes  = [cv2.getTextSize(l, font, font_scale, thickness)[0] for l in lines]
    w      = max(s[0] for s in sizes) + 8
    line_h = max(s[1] for s in sizes) + 5
    h      = line_h * len(lines) + 6
    img    = np.zeros((h, w, 3), dtype=np.uint8)
    y      = 3 + sizes[0][1]
    for l in lines:
        cv2.putText(img, l, (4, y), font, font_scale, (255,255,255), thickness, cv2.LINE_AA)
        y += line_h
    if img.shape[0] > max_h:
        sc  = max_h / img.shape[0]
        img = cv2.resize(img, (max(1, int(img.shape[1]*sc)), max_h), cv2.INTER_NEAREST)
    if len(_tb_cache) < 64:
        _tb_cache[key] = img
    return img

# ============================================================
#  BUTTON DRAWING
# ============================================================
def draw_film_button(canvas, name, accent_bgr, is_default, x, y):
    w, h = FILM_BTN_W, FILM_BTN_H
    ch_h, cw = canvas.shape[:2]
    if x+w > cw: w = cw-x
    if y+h > ch_h: h = ch_h-y
    if w <= 0 or h <= 0: return (x, y, x, y)
    canvas[y:y+h, x:x+w] = cv2.convertScaleAbs(canvas[y:y+h, x:x+w], alpha=0.40)
    cv2.rectangle(canvas, (x,y), (x+w-1,y+h-1), accent_bgr, 2)
    perf_w, perf_h = 6, 5
    n_perfs = max(2, h//12); spacing = h//(n_perfs+1)
    for i in range(n_perfs):
        fy = y + spacing*(i+1) - perf_h//2
        cv2.rectangle(canvas, (x+4,fy), (x+4+perf_w,fy+perf_h), accent_bgr, -1)
    font = cv2.FONT_HERSHEY_SIMPLEX; fscale = 0.50
    (_, th), _ = cv2.getTextSize(name[:16], font, fscale, 1)
    cv2.putText(canvas, name[:16], (x+4+perf_w+8, y+(h+th)//2), font, fscale, (255,255,255), 1, cv2.LINE_AA)
    cx, cy = x + w - 17, y + h // 2
    angles = np.arange(10) * np.pi / 5 - np.pi / 2
    radii = np.tile([10, 4], 5)
    points = np.column_stack((cx + radii * np.cos(angles),
                              cy + radii * np.sin(angles))).astype(np.int32)
    if is_default:
        cv2.fillPoly(canvas, [points], accent_bgr)
    else:
        cv2.polylines(canvas, [points], True, (180, 180, 180), 1, cv2.LINE_AA)
    return (x, y, x+w, y+h)

def draw_toggle_button(canvas, label, is_active, x, y, width=FILM_BTN_W):
    w, h = width, FILM_BTN_H
    ch_h, cw = canvas.shape[:2]
    if x+w > cw: w = cw-x
    if y+h > ch_h: h = ch_h-y
    if w <= 0 or h <= 0: return (x, y, x, y)
    canvas[y:y+h, x:x+w] = cv2.convertScaleAbs(canvas[y:y+h, x:x+w], alpha=0.40)
    accent = (0,200,0) if is_active else (100,100,100)
    cv2.rectangle(canvas, (x,y), (x+w-1,y+h-1), accent, 2)
    font = cv2.FONT_HERSHEY_SIMPLEX; fscale = 0.50
    (tw, th), _ = cv2.getTextSize(label, font, fscale, 1)
    color = (255,255,255) if is_active else (150,150,150)
    cv2.putText(canvas, label, (x+(w-tw)//2, y+(h+th)//2), font, fscale, color, 1, cv2.LINE_AA)
    return (x, y, x+w, y+h)

def draw_photo_button(canvas, label, x, y):
    w, h = PHOTO_BTN_W, PHOTO_BTN_H
    canvas[y:y+h, x:x+w] = cv2.convertScaleAbs(canvas[y:y+h, x:x+w], alpha=0.40)
    cv2.rectangle(canvas, (x, y), (x+w-1, y+h-1), (210, 210, 210), 2)
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), _ = cv2.getTextSize(label, font, 0.46, 1)
    cv2.putText(canvas, label, (x+(w-tw)//2, y+(h+th)//2), font, 0.46,
                (255, 255, 255), 1, cv2.LINE_AA)
    return (x, y, x+w, y+h)

_shutter_outer_mask = np.zeros((SHUTTER_BTN_SIZE, SHUTTER_BTN_SIZE), dtype=np.uint8)
_shutter_inner_mask = np.zeros_like(_shutter_outer_mask)
_shutter_white = np.full((SHUTTER_BTN_SIZE, SHUTTER_BTN_SIZE, 3), 235, dtype=np.uint8)
cv2.circle(_shutter_outer_mask, (SHUTTER_BTN_SIZE//2, SHUTTER_BTN_SIZE//2),
           SHUTTER_BTN_SIZE//2-1, 255, -1)
cv2.circle(_shutter_inner_mask, (SHUTTER_BTN_SIZE//2, SHUTTER_BTN_SIZE//2),
           SHUTTER_BTN_SIZE//2-10, 255, -1)

def draw_shutter_button(canvas, x, y):
    """Dim only the round button area, leaving its square corners clear."""
    size = SHUTTER_BTN_SIZE
    roi = canvas[y:y+size, x:x+size]
    dim = cv2.convertScaleAbs(roi, alpha=0.42)
    cv2.copyTo(dim, _shutter_outer_mask, roi)
    fill = cv2.addWeighted(roi, 0.55, _shutter_white, 0.45, 0)
    cv2.copyTo(fill, _shutter_inner_mask, roi)
    c = size // 2
    cv2.circle(roi, (c, c), c-2, (245, 245, 245), 3, cv2.LINE_AA)
    return (x, y, x+size, y+size)

def _get_control_tile(kind, label, state=None, accent=None):
    """Render each control state once; only composite its tile per frame."""
    key = (kind, label, state, accent)
    tile = _control_cache.get(key)
    if tile is not None:
        return tile
    if kind == "photo":
        tile = np.zeros((PHOTO_BTN_H, PHOTO_BTN_W, 3), dtype=np.uint8)
        draw_photo_button(tile, label, 0, 0)
    elif kind == "peak":
        tile = np.zeros((FILM_BTN_H, PEAK_BTN_W, 3), dtype=np.uint8)
        draw_toggle_button(tile, label, bool(state), 0, 0, width=PEAK_BTN_W)
    elif kind == "sleep":
        tile = np.zeros((FILM_BTN_H, PEAK_BTN_W, 3), dtype=np.uint8)
        draw_toggle_button(tile, label, False, 0, 0, width=PEAK_BTN_W)
    else:
        tile = np.zeros((FILM_BTN_H, FILM_BTN_W, 3), dtype=np.uint8)
        if kind == "film":
            draw_film_button(tile, label, accent, bool(state), 0, 0)
        else:
            draw_toggle_button(tile, label, bool(state), 0, 0)
    _control_cache[key] = tile
    return tile

def _place_control(canvas, tile, x, y):
    h, w = tile.shape[:2]
    roi = canvas[y:y+h, x:x+w]
    cv2.addWeighted(roi, 0.40, tile, 1.0, 0, dst=roi)
    return (x, y, x+w, y+h)

def _set_bounds(bounds, rect):
    x1, y1, x2, y2 = rect
    bounds.update({"bx1": x1, "by1": y1, "bx2": x2, "by2": y2})

# ============================================================
#  CAMERA SETUP
#
#  One YUV420 still buffer limits contiguous camera-memory use on the Zero.
#  Four preview buffers keep the live stream from stalling while CPU work runs.
# ============================================================
from libcamera import Transform

picam2 = Picamera2()

DEFAULT_FRAME_LIMITS = (125, 16667)

preview_config = picam2.create_preview_configuration(
    main={"size": (SCREEN_W, SCREEN_H), "format": "RGB888"},
    lores=None, raw=None, display=None,
    buffer_count=4,
    queue=False,
    #transform=Transform(rotation=270),  # correct 270° CCW sensor rotation
    controls={
        "AeMeteringMode":      2,
        "NoiseReductionMode":  0,
        "FrameDurationLimits": DEFAULT_FRAME_LIMITS,
    }
)

still_configs = {}
for photo_name, photo_size in PHOTO_MODES:
    still_configs[photo_name] = picam2.create_still_configuration(
        main={"size": photo_size, "format": "YUV420"},
        raw=None, buffer_count=1,
        #transform=Transform(rotation=270),  # same correction for stills
        controls={
            "AeMeteringMode":      2,
            "NoiseReductionMode":  0,
            "FrameDurationLimits": DEFAULT_FRAME_LIMITS,
        }
    )

picam2.configure(preview_config)
picam2.options["quality"] = JPEG_QUALITY
picam2.start()
picam2.set_controls({"FrameDurationLimits": DEFAULT_FRAME_LIMITS})
time.sleep(1)

# ============================================================
#  SHUTTER CONTROL (GPIO26)
# ============================================================
SHUTTER_OPTIONS_US = [None, 33333, 16667, 8000, 4000, 2000, 1000, 500, 250]
SHUTTER_LABELS     = ["Auto","1/30","1/60","1/125","1/250","1/500","1/1000","1/2000","1/4000"]

current_shutter_idx = 0
shutter_set_mode    = False
_hold_fired         = False
shoot_event         = threading.Event()

def _apply_shutter():
    us = SHUTTER_OPTIONS_US[current_shutter_idx]
    if us is None:
        picam2.set_controls({"AeEnable": True, "FrameDurationLimits": DEFAULT_FRAME_LIMITS})
    else:
        picam2.set_controls({"AeEnable": False, "ExposureTime": int(us),
                             "FrameDurationLimits": (int(us), int(us))})

def _toggle_shutter_set():
    global shutter_set_mode
    shutter_set_mode = not shutter_set_mode
    print(f"[Shutter Set] {'ON' if shutter_set_mode else 'OFF'} – {SHUTTER_LABELS[current_shutter_idx]}")
    _apply_shutter()

def _cycle_shutter():
    global current_shutter_idx
    current_shutter_idx = (current_shutter_idx + 1) % len(SHUTTER_OPTIONS_US)
    print(f"[Shutter] {SHUTTER_LABELS[current_shutter_idx]}")
    _apply_shutter()

button = None

def _on_held():
    global _hold_fired
    _hold_fired = True
    _toggle_shutter_set()

try:
    button = Button(26, pull_up=True, bounce_time=0.05, hold_time=2.0)
    button.when_held     = _on_held
    button.when_released = _on_released
    button.when_pressed  = _on_pressed
except Exception as error:
    print(f"[GPIO] Physical shutter unavailable; screen shutter remains active: {error}", flush=True)
    button = None

# ============================================================
#  DISPLAY + TOUCH
# ============================================================
cv2.namedWindow("Camera", cv2.WND_PROP_FULLSCREEN)
cv2.setWindowProperty("Camera", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)
cv2.moveWindow("Camera", 0, 0)
cv2.setWindowProperty("Camera", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
cv2.setMouseCallback("Camera", _on_mouse)

# ============================================================
#  MAIN LOOP
# ============================================================

def _apply_current_camera_controls():
    picam2.set_controls({
        "AeMeteringMode": METERING_MODES[current_meter_idx][1],
        "ExposureValue": EV_OPTIONS[current_ev_idx],
        "AwbMode": AWB_MODES[current_awb_idx][1],
    })
    _apply_shutter()

def _restore_preview_camera():
    picam2.configure(preview_config)
    _apply_current_camera_controls()
    picam2.start()

# The configuration carries safe startup defaults; align the running preview
# with the labels selected by the UI before entering the loop.
_apply_current_camera_controls()

def _show_processing(photo_name):
    _canvas.fill(18)
    cv2.putText(_canvas, f"Processing {photo_name}...", (74, 154),
                cv2.FONT_HERSHEY_SIMPLEX, 0.82, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(_canvas, "Preview camera restarted", (112, 185),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (170, 170, 170), 1, cv2.LINE_AA)
    cv2.imshow("Camera", _canvas)
    cv2.waitKey(1)

def _zoom_preview(frame):
    """Return an exact 480x320 view; do no resize at the normal 1x path."""
    if current_zoom_idx == 0 and frame.shape[:2] == (SCREEN_H, SCREEN_W):
        return frame

    zoom = zoom_levels[current_zoom_idx]
    if zoom > 1.0:
        fh, fw = frame.shape[:2]
        crop_w = max(1, int(round(fw / zoom)))
        crop_h = max(1, int(round(fh / zoom)))
        cx = int(round(zoom_center[0] * (fw - 1)))
        cy = int(round(zoom_center[1] * (fh - 1)))
        # Clamp the crop origin, not only its far edge, so taps near an edge
        # still produce the requested crop size and zoom factor.
        x1 = min(max(0, cx - crop_w // 2), fw - crop_w)
        y1 = min(max(0, cy - crop_h // 2), fh - crop_h)
        frame = frame[y1:y1+crop_h, x1:x1+crop_w]

    if frame.shape[:2] != (SCREEN_H, SCREEN_W):
        frame = cv2.resize(frame, (SCREEN_W, SCREEN_H), interpolation=cv2.INTER_NEAREST)
    return frame

def _profile_preview(frame):
    if current_profile_idx == 0:
        return frame
    small = cv2.resize(frame, (PROFILE_W, PROFILE_H), interpolation=cv2.INTER_AREA)
    small = apply_current_profile(small, preview=True)
    return cv2.resize(small, (SCREEN_W, SCREEN_H), interpolation=cv2.INTER_NEAREST)

_perf_window_start = time.monotonic()
_perf_frames = 0
_perf_totals = {"acquisition": 0.0, "profile": 0.0, "peak_detect": 0.0,
                "peak_overlay": 0.0, "ui": 0.0, "display": 0.0, "frame_age": 0.0}

def _reset_preview_perf():
    global _perf_window_start, _perf_frames
    _perf_window_start = time.monotonic()
    _perf_frames = 0
    for key in _perf_totals:
        _perf_totals[key] = 0.0

def _record_preview_perf(**timings):
    global _perf_frames
    _perf_frames += 1
    for key, value in timings.items():
        _perf_totals[key] += value

def _maybe_log_preview_perf():
    elapsed = time.monotonic() - _perf_window_start
    if elapsed < PERF_LOG_SECS or _perf_frames == 0:
        return
    scale = 1000.0 / _perf_frames
    print(
        f"[Perf] displayed={_perf_frames / elapsed:.1f} fps "
        f"acquisition={_perf_totals['acquisition'] * scale:.1f} ms "
        f"profile={_perf_totals['profile'] * scale:.1f} ms "
        f"peak-detect={_perf_totals['peak_detect'] * scale:.1f} ms "
        f"peak-overlay={_perf_totals['peak_overlay'] * scale:.1f} ms "
        f"ui={_perf_totals['ui'] * scale:.1f} ms "
        f"display={_perf_totals['display'] * scale:.1f} ms "
        f"frame-age={_perf_totals['frame_age'] * scale:.1f} ms",
        flush=True,
    )
    _reset_preview_perf()

_ui_frame_idx    = 0
_last_tb_state   = None
_cached_tb_img   = None
_cached_hist_img = None
_last_control_state = None
_cached_controls = None

while True:
    # Power-off hold (10 s)
    if button is not None and button.is_pressed and press_start_time > 0 and (time.time() - press_start_time) >= 10.0:
        print("[System] Powering off...")
        _canvas.fill(0)
        cv2.putText(_canvas, "Shutting down...", (80, 160),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255,255,255), 2, cv2.LINE_AA)
        cv2.imshow("Camera", _canvas)
        cv2.waitKey(100)
        os.system("sudo poweroff")
        break

    # Sleep mode
    if sleep_mode:
        _canvas.fill(0)
        cv2.imshow("Camera", _canvas)
        cv2.waitKey(1)
        time.sleep(0.2)
        _reset_preview_perf()
        continue

    # ---- Capture still ----
    if shoot_event.is_set():
        shoot_event.clear()
        capture_busy = True
        capture_started = time.monotonic()
        dt = datetime.now().strftime("%Y%m%d_%H%M%S")
        shot_profile_idx = current_profile_idx
        shot_profile_name = FILM_PROFILES[shot_profile_idx][0]
        tag = shot_profile_name.replace(" ", "_")
        photo_name, photo_size = PHOTO_MODES[current_photo_idx]
        shot_pro_mist = pro_mist_enabled
        fast_standard = shot_profile_idx == 0 and not shot_pro_mist
        fast_warm = shot_profile_idx in _WARM_YUV_STYLES and not shot_pro_mist
        preview_restored = False
        acquire_secs = restart_secs = process_secs = encode_secs = 0.0
        raw = processed = still_arrays = request = jpg_data = None
        yuv_y = yuv_u = yuv_v = None
        try:
            acquire_start = time.monotonic()
            # Free all preview DMA buffers before allocating one still buffer.
            picam2.stop()
            picam2.configure(still_configs[photo_name])
            _apply_current_camera_controls()
            picam2.start()
            if fast_standard:
                request = picam2.capture_request()
                meta = request.get_metadata()
            else:
                # capture_arrays already owns one copy; do not copy it again.
                still_arrays, meta = picam2.capture_arrays(["main"])
                raw = still_arrays[0]
            acquire_secs = time.monotonic() - acquire_start

            iso = int(meta.get("AnalogueGain", 1) * 100)
            shutter = format_shutter(meta.get("ExposureTime", 0)).replace("/", "_")
            jpg_path = f"{PICTURES_DIR}/{dt}_{tag}_ISO{iso}_{shutter}.jpg"

            if fast_standard:
                encode_start = time.monotonic()
                request.save("main", jpg_path)
                encode_secs = time.monotonic() - encode_start
                request.release()
                request = None

            restart_start = time.monotonic()
            picam2.stop()
            _restore_preview_camera()
            preview_restored = True
            restart_secs = time.monotonic() - restart_start
            if not fast_standard:
                _show_processing(photo_name)
                process_start = time.monotonic()
                if fast_warm:
                    yuv_y, yuv_u, yuv_v = style_yuv_planes(raw, photo_size, shot_profile_idx)
                else:
                    # Convert after restoring preview, in ordinary RAM.
                    raw = cv2.cvtColor(raw, cv2.COLOR_YUV2BGR_I420)
                    raw = raw[:photo_size[1], :photo_size[0]]
                    still_arrays = None
                    processed = FILM_PROFILES[shot_profile_idx][1](raw, preview=False)
                    if shot_pro_mist:
                        processed = apply_pro_mist(processed)
                process_secs = time.monotonic() - process_start

                encode_start = time.monotonic()
                if fast_warm:
                    jpg_data = simplejpeg.encode_jpeg_yuv_planes(
                        yuv_y, yuv_u, yuv_v, JPEG_QUALITY, fastdct=True)
                else:
                    jpg_data = simplejpeg.encode_jpeg(
                        np.ascontiguousarray(processed), quality=JPEG_QUALITY,
                        colorspace="BGR", colorsubsampling="420", fastdct=True,
                    )
                with open(jpg_path, "wb") as photo_file:
                    photo_file.write(jpg_data)
                encode_secs = time.monotonic() - encode_start
            image_count += 1
            print(f"Captured {jpg_path} ({photo_size[0]}x{photo_size[1]}, #{image_count})", flush=True)

        except Exception as e:
            print("Capture error:", e); traceback.print_exc()

        finally:
            if request is not None:
                request.release()
            # Always return to preview, even on failure
            if not preview_restored:
                try:
                    picam2.stop()
                except Exception:
                    pass
                try:
                    _restore_preview_camera()
                    preview_restored = True
                except Exception as recovery_error:
                    print("Preview recovery error:", recovery_error)
                    traceback.print_exc()
            total_secs = time.monotonic() - capture_started
            print(
                f"[Capture Perf] {photo_name} acquire={acquire_secs:.2f}s "
                f"preview-restart={restart_secs:.2f}s process={process_secs:.2f}s "
                f"jpeg-q{JPEG_QUALITY}={encode_secs:.2f}s total={total_secs:.2f}s",
                flush=True,
            )
            current_zoom_idx = 0
            _cached_hist_img = None
            # Top-level loop variables otherwise retain the large arrays until
            # the next shot on CPython.
            raw = processed = still_arrays = request = jpg_data = None
            yuv_y = yuv_u = yuv_v = None
            shoot_event.clear()
            capture_busy = False
            _reset_preview_perf()

        if not preview_restored:
            print("[Camera] Preview could not be recovered; exiting cleanly.")
            break

    # ---- Preview frame ----
    acquisition_start = time.monotonic()
    preview_arrays, meta = picam2.capture_arrays(["main"])
    acquisition_secs = time.monotonic() - acquisition_start

    # ---- Film profile (fast preview path) ----
    profile_start = time.monotonic()
    frame = _zoom_preview(preview_arrays[0])
    profiled = _profile_preview(frame)
    profile_secs = time.monotonic() - profile_start

    # ---- Focus peaking on the exact frame being displayed ----
    peaking_start = time.monotonic()
    if focus_peaking_enabled:
        peak_mask = make_focus_peaking_mask(frame)
        peak_detect_secs = time.monotonic() - peaking_start
        disp = apply_focus_peaking_mask(profiled, peak_mask)
        peak_overlay_secs = time.monotonic() - peaking_start - peak_detect_secs
    else:
        disp = profiled
        peak_detect_secs = peak_overlay_secs = 0.0

    # ---- Refresh approximate UI data every few frames ----
    ui_start = time.monotonic()
    _ui_frame_idx += 1
    if _ui_frame_idx % UI_EVERY == 0 or _cached_hist_img is None:
        gray_hist = cv2.cvtColor(profiled, cv2.COLOR_BGR2GRAY)
        _cached_hist_img = draw_histogram(gray_hist, height=BAR_H, width=_HIST_W)

        shutter_text = format_shutter(meta.get("ExposureTime", 0))
        iso_text = f"ISO{int(meta.get('AnalogueGain', 0) * 100)}"
        status_text = "SET" if shutter_set_mode else "RDY"
        current_tb_state = (
            f"{status_text} {SHUTTER_LABELS[current_shutter_idx]}",
            f"{shutter_text} {iso_text} #{image_count}",
        )
        if current_tb_state != _last_tb_state:
            _last_tb_state = current_tb_state
            _cached_tb_img = make_text_block(list(current_tb_state), max_h=BAR_H-6)

    # Control labels are cheap cached tiles; update on the very next frame.
    name, _, accent = FILM_PROFILES[current_profile_idx]
    photo_label = f"Photo: {PHOTO_MODES[current_photo_idx][0]}"
    pm_label = "Pro-Mist: ON" if pro_mist_enabled else "Pro-Mist: OFF"
    meter_name = METERING_MODES[current_meter_idx][0]
    ev_val = EV_OPTIONS[current_ev_idx]
    awb_name = AWB_MODES[current_awb_idx][0]
    control_state = (name, accent, current_profile_idx == default_profile_idx,
                     photo_label, pm_label, pro_mist_enabled, meter_name, ev_val,
                     awb_name, focus_peaking_enabled)
    if control_state != _last_control_state:
        _last_control_state = control_state
        _cached_controls = (
            _get_control_tile("film", name, state=current_profile_idx == default_profile_idx, accent=accent),
            _get_control_tile("photo", photo_label),
            _get_control_tile("toggle", pm_label, state=pro_mist_enabled),
            _get_control_tile("toggle", f"Meter: {meter_name}", state=True),
            _get_control_tile("toggle", f"EV: {ev_val:+}", state=True),
            _get_control_tile("toggle", f"WB: {awb_name}", state=True),
            _get_control_tile("peak", "PEAK", state=focus_peaking_enabled),
            _get_control_tile("sleep", "SLEEP"),
        )

    # ---- Compose cached UI assets into the current frame ----
    _canvas[:] = disp
    bar_y = SCREEN_H - BAR_H
    cv2.convertScaleAbs(_canvas[bar_y:SCREEN_H], dst=_canvas[bar_y:SCREEN_H], alpha=0.75)
    blit_add(_canvas, _cached_hist_img, 6, bar_y)
    blit_add(_canvas, _cached_tb_img, 6+_HIST_W+8,
             bar_y+(BAR_H-_cached_tb_img.shape[0])//2)

    film_tile, photo_tile, pm_tile, meter_tile, ev_tile, awb_tile, peak_tile, sleep_tile = _cached_controls
    for row, (tile, bounds) in enumerate(((film_tile, btn_bounds),
                                          (pm_tile, btn_bounds_pm),
                                          (meter_tile, btn_bounds_meter),
                                          (ev_tile, btn_bounds_ev),
                                          (awb_tile, btn_bounds_awb))):
        y = EDGE_INSET + row * (FILM_BTN_H + CONTROL_GAP)
        _set_bounds(bounds, _place_control(_canvas, tile, EDGE_INSET, y))

    photo_x = SCREEN_W - PHOTO_BTN_W - EDGE_INSET
    _set_bounds(btn_bounds_photo, _place_control(_canvas, photo_tile, photo_x, EDGE_INSET))
    peak_x = SCREEN_W - PEAK_BTN_W - EDGE_INSET
    _set_bounds(btn_bounds_peak, _place_control(_canvas, peak_tile, peak_x,
                                                EDGE_INSET + PHOTO_BTN_H + CONTROL_GAP))
    shutter_x = SCREEN_W - SHUTTER_BTN_SIZE - EDGE_INSET
    _set_bounds(btn_bounds_shutter, draw_shutter_button(_canvas, shutter_x,
                                                       SCREEN_H - BAR_H - SHUTTER_BTN_SIZE - EDGE_INSET))
    _set_bounds(btn_bounds_sleep, _place_control(_canvas, sleep_tile, peak_x,
                                                 EDGE_INSET + 2 * (PHOTO_BTN_H + CONTROL_GAP)))

    ui_secs = time.monotonic() - ui_start
    sensor_ts = meta.get("SensorTimestamp")
    frame_age_secs = max(0.0, (time.monotonic_ns() - sensor_ts) / 1e9) if isinstance(sensor_ts, int) else 0.0
    display_start = time.monotonic()
    cv2.imshow("Camera", _canvas)
    key = cv2.waitKey(1)
    display_secs = time.monotonic() - display_start
    _record_preview_perf(acquisition=acquisition_secs, profile=profile_secs,
                         peak_detect=peak_detect_secs, peak_overlay=peak_overlay_secs,
                         ui=ui_secs, display=display_secs, frame_age=frame_age_secs)
    _maybe_log_preview_perf()
    if key == 27:
        break

cv2.destroyAllWindows()
try:
    picam2.stop()
except Exception:
    pass
