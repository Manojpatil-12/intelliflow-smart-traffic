"""
YOLOv8 detection service — LAZY LOADED.
The model is instantiated on first request, never at Django boot.
If ultralytics is not installed, returns None gracefully.
Uses subprocess for detection to avoid blocking Daphne's ASGI event loop.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("vision.yolo")

_available = None


def is_available():
    """Check if ultralytics is importable."""
    global _available
    if _available is None:
        try:
            import ultralytics  # noqa: F401
            _available = True
        except ImportError:
            _available = False
            logger.info("ultralytics not installed — vision module unavailable")
    return _available


# Standalone detection script run as a subprocess
_DETECT_SCRIPT = '''
import json
import sys

image_path = sys.argv[1]

from ultralytics import YOLO
model = YOLO("yolov8n.pt")
results = model(str(image_path), verbose=False, imgsz=320)
result = results[0]

VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
counts = {}
raw = []
for box in result.boxes:
    cls_id = int(box.cls[0])
    conf = float(box.conf[0])
    name = result.names.get(cls_id, f"class_{cls_id}")
    if cls_id in VEHICLE_CLASSES:
        vehicle_name = VEHICLE_CLASSES[cls_id]
        counts[vehicle_name] = counts.get(vehicle_name, 0) + 1
    raw.append({"class_id": cls_id, "class_name": name, "confidence": round(conf, 3), "bbox": box.xyxy[0].tolist()})

total = sum(counts.values())
emergency = any(kw in d["class_name"].lower() for d in raw for kw in ("ambulance", "fire", "police"))

# Save annotated image
from pathlib import Path
annotated_dir = Path(image_path).parent / "annotated"
annotated_dir.mkdir(exist_ok=True)
annotated_path = str(annotated_dir / Path(image_path).name)
try:
    import cv2
    annotated_img = result.plot()
    cv2.imwrite(annotated_path, annotated_img)
except Exception:
    annotated_path = image_path

output = {"counts": counts, "total": total, "emergency_detected": emergency, "annotated_path": annotated_path, "raw_detections": raw}
print(json.dumps(output))
'''


def detect_vehicles(image_path):
    """
    Run detection in a subprocess to avoid blocking the ASGI event loop.
    Returns dict with counts, total, emergency_detected, annotated_path.
    """
    if not is_available():
        return None

    try:
        proc = subprocess.run(
            [sys.executable, "-c", _DETECT_SCRIPT, str(image_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            logger.error("YOLO subprocess failed: %s", proc.stderr[-500:] if proc.stderr else "no stderr")
            return None

        # Parse JSON from last line of stdout
        stdout = proc.stdout.strip()
        lines = stdout.split("\n")
        result_line = lines[-1]
        result = json.loads(result_line)
        logger.info("Detection complete: %d vehicles found", result["total"])
        return result

    except subprocess.TimeoutExpired:
        logger.error("YOLO detection timed out after 60s")
        return None
    except (json.JSONDecodeError, Exception) as e:
        logger.error("YOLO detection error: %s", e)
        return None
