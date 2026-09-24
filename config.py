import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
APP_NAME = 'NEXO'
APP_SUBTITLE = 'Sistema de búsqueda y monitoreo'
HOST = os.getenv('NEXO_HOST', '127.0.0.1')
PORT = int(os.getenv('NEXO_PORT', '8080'))
DEMO_DATE = '2026-09-23'
DATA_DIR = BASE_DIR / 'data'
# Token público de Mapbox (pk.*): viaja al navegador para descargar el mapa base.
MAPBOX_TOKEN = os.getenv('NEXO_MAPBOX_TOKEN', '')

VOICE_MODEL = os.getenv('VOICE_MODEL', 'base')
VOICE_LANGUAGE = 'es'
VOICE_DEMO_MODE = os.getenv('VOICE_DEMO_MODE', 'true').lower() in ('true', '1', 'yes')
AUDIO_SAMPLE_RATE = 16000
AUDIO_MAX_SECONDS = 60
CONTEXT_SECONDS = 20
CONTEXT_MAX_SEGMENTS = 8
CONTEXT_MAX_TEXT = 2000
AUDIO_WINDOW_SECONDS = 6
AUDIO_OVERLAP_SECONDS = 2
AI_CONTEXT_ENABLED = os.getenv('AI_CONTEXT_ENABLED', 'true').lower() in ('true', '1', 'yes')
AI_PROVIDER = os.getenv('AI_PROVIDER', 'ollama')
AI_MODEL = os.getenv('AI_MODEL', 'qwen2.5:3b')
AI_CONTEXT_URL = os.getenv('AI_CONTEXT_URL', 'http://127.0.0.1:11434')
AI_TIMEOUT_SECONDS = 15
ACOUSTIC_CHANGE_RATIO = 2.0
VOICE_RELEVANT_HISTORY_LIMIT = 100

# Continuous monitoring and evidence retention.
EVIDENCE_DIR = BASE_DIR / 'evidence'
EVIDENCE_AUDIO_DIR = EVIDENCE_DIR / 'audio'
EVIDENCE_VIDEO_DIR = EVIDENCE_DIR / 'video'
EVIDENCE_PRE_SECONDS = 10
EVIDENCE_POST_SECONDS = 10
# Ring buffer: pre-roll + window + post-roll with margin. Nothing older is kept.
AUDIO_RING_SECONDS = EVIDENCE_PRE_SECONDS + AUDIO_WINDOW_SECONDS + EVIDENCE_POST_SECONDS + 15
DEFAULT_CAMERA_ID = os.getenv('NEXO_CAMERA', 'CAM-008')
SECOND_CAMERA_ID = os.getenv('NEXO_CAMERA_2', 'CAM-007')

# Importación de alertas de búsqueda: archivos temporales, nunca evidencia.
IMPORT_DIR = BASE_DIR / 'imports'
IMPORT_DOCUMENTS_DIR = IMPORT_DIR / 'documents'
IMPORT_PHOTOS_DIR = IMPORT_DIR / 'photos'
IMPORT_MAX_BYTES = 10 * 1024 * 1024
IMPORT_RENDER_DPI = 200
IMPORT_DATE_WINDOW_DAYS = 15
OCR_LANGUAGE = os.getenv('OCR_LANGUAGE', 'spa')

# Reconocimiento facial con InsightFace. Los modelos preentrenados son de uso no comercial.
FACE_MODEL = os.getenv('FACE_MODEL', 'buffalo_l')
# Fuera del proyecto: el modelo pesa ~330 MB y no debe viajar en el repositorio ni en los ZIP.
FACE_MODEL_ROOT = Path(os.getenv('FACE_MODEL_ROOT', '~/.insightface')).expanduser()
FACE_AUTO_DOWNLOAD = os.getenv('FACE_AUTO_DOWNLOAD', 'true').lower() in ('true', '1', 'yes')
FACE_MIN_DET_SCORE = 0.5
# Similitud coseno entre huellas de buffalo_l. Orientativa: siempre requiere revisión humana.
FACE_MATCH_THRESHOLD = 0.45
FACE_LEVEL_MEDIUM = 0.50
FACE_LEVEL_HIGH = 0.60

# Reconocimiento en vivo: la webcam del equipo donde corre NEXO, asociada a una cámara de la red.
CAMERA_INDEX = int(os.getenv('NEXO_CAMERA_INDEX', '0'))
CAMERA_INDEX_2 = int(os.getenv('NEXO_CAMERA_INDEX_2', '1'))
# Una detección por caso y cámara en cada ventana; dentro de ella se conserva la mejor captura.
LIVE_DETECTION_COOLDOWN_SECONDS = 30
LIVE_GALLERY_REFRESH_SECONDS = 2
LIVE_ANALYSIS_INTERVAL_SECONDS = .15
