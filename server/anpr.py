"""Kennzeichenerkennung. Nutzt fast-alpr, falls installiert."""
import re
_alpr = None

def _load():
    global _alpr
    if _alpr is None:
        from fast_alpr import ALPR
        _alpr = ALPR(
            detector_model="yolo-v9-t-384-license-plate-end2end",
            ocr_model="global-plates-mobile-vit-v2-model",
        )
    return _alpr

def read_plate(jpeg_bytes: bytes) -> str:
    try:
        import cv2, numpy as np
        frame = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
        results = _load().predict(frame)
        if not results:
            return ""
        best = max(results, key=lambda r: r.ocr.confidence if r.ocr else 0)
        return re.sub(r"[^A-Z0-9]", "", best.ocr.text.upper())
    except Exception as e:
        print("ANPR error:", e)
        return ""
