"""Configuración del servicio FastAPI desde el entorno."""

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
# Modelo distribuido con la aplicación; no depende del dataset ni de training/runs/.
DEFAULT_DETECTOR_WEIGHTS = APP_DIR.parents[1] / "models" / "detector" / "best.pt"
VISION_SERVICE_TOKEN_SECRET = os.getenv("VISION_SERVICE_TOKEN_SECRET", "")
DETECTOR_WEIGHTS = os.getenv("DETECTOR_WEIGHTS") or str(DEFAULT_DETECTOR_WEIGHTS)
COLOR_MODEL_PATH = os.getenv("COLOR_MODEL_PATH", "")
WEIGHT_MODEL_PATH = os.getenv("WEIGHT_MODEL_PATH", "")
TRACK_IOU_THRESHOLD = float(os.getenv("TRACK_IOU_THRESHOLD", "0.3"))
COUNT_LINE_RATIO = float(os.getenv("COUNT_LINE_RATIO", "0.5"))
# En vídeo, un track solo se registra como camarón tras aparecer en este número de fotogramas.
VIDEO_MIN_TRACK_HITS = int(os.getenv("VIDEO_MIN_TRACK_HITS", "3"))
# Ningún cuadro de entrenamiento supera el 40 % del área de la imagen; mayores se rechazan.
MAX_BOX_AREA_RATIO = float(os.getenv("MAX_BOX_AREA_RATIO", "0.45"))
