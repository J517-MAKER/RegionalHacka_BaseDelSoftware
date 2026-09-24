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
# Una detección por caso y cámara en cada ventana; dentro de ella se conserva la mejor captura.
LIVE_DETECTION_COOLDOWN_SECONDS = 30
LIVE_GALLERY_REFRESH_SECONDS = 2
LIVE_ANALYSIS_INTERVAL_SECONDS = .15

# --------------------------------------------------------------- monitoreo continuo
# Las cámaras se consideran activas por sí mismas: nadie las "inicia" desde la interfaz.
# La webcam del equipo es una fuente más; las demás son fuentes simuladas.
# Se consulta a menudo para que el fragmento conservado tenga fluidez suficiente.
CAMERA_STREAM_POLL_SECONDS = 0.2
CAMERA_STALE_SECONDS = 90
# Ventana de video conservada alrededor de un evento. Fuera de ella el anillo se sobrescribe.
VIDEO_PRE_EVENT_SECONDS = 10
VIDEO_POST_EVENT_SECONDS = 10
VIDEO_RING_SECONDS = VIDEO_PRE_EVENT_SECONDS + VIDEO_POST_EVENT_SECONDS + 10
VIDEO_RING_FPS = 5
# Margen al buscar el fotograma más próximo a cada instante pedido.
EVENT_FRAME_TOLERANCE_SECONDS = 1.0
# Un solo fotograma puede salir borroso o de perfil: se toman varios alrededor del evento.
EVENT_FRAME_OFFSETS_SECONDS = (0, 1, 2, 3, 5)

# ------------------------------------------------------- motor de búsqueda multimodal
# La hora de desaparición marca el inicio de la ventana prioritaria; nada se descarta por tiempo.
SEARCH_UNKNOWN_TIME_TOLERANCE_HOURS = 12
SEARCH_PRIORITY_WINDOW_DAYS = 7
# Distancia en el plano de demostración; la cercanía prioriza, nunca excluye.
SEARCH_NEAR_DISTANCE = 18.0
SEARCH_FAR_DISTANCE = 45.0
# Continuidad entre cámaras relacionadas: dos apariciones compatibles dentro de esta ventana.
SEARCH_ROUTE_WINDOW_MINUTES = 20
# Prioridad de revisión, no probabilidad de identidad.
CANDIDATE_PRIORITY_THRESHOLD = 0.55
CANDIDATE_MAX_RESULTS = 25

# La cámara del equipo se incorpora al monitoreo continuo por sí sola. Se puede desactivar
# (NEXO_CAMERA_AUTOSTART=false) en equipos donde la webcam se necesite para otra cosa.
CAMERA_AUTOSTART = os.getenv('NEXO_CAMERA_AUTOSTART', 'true').lower() in ('true', '1', 'yes')
CAMERA_AUTOSTART_RETRY_SECONDS = 20
# Una webcam virtual sin señal entrega cuadros completamente negros: no sirve como fuente.
CAMERA_AUTO_DEVICE = os.getenv('NEXO_CAMERA_AUTO_DEVICE', 'true').lower() in ('true', '1', 'yes')
CAMERA_PROBE_MAX_INDEX = 4
CAMERA_PROBE_MIN_BRIGHTNESS = 1.0

# Si el análisis se queda más atrás que esto, se salta al presente en vez de arrastrar el
# retraso: es preferible perder un fragmento antiguo que escuchar siempre con demora.
AUDIO_MAX_LAG_SECONDS = 8
