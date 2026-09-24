import os
import socket
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def load_env_file(path=BASE_DIR / '.env'):
    """Variables locales (tokens) desde .env, que nunca se sube a git; las del sistema mandan."""
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            name, value = line.split('=', 1)
            value = value.split(' #', 1)[0].split('\t#', 1)[0]  # comentario al final de la línea
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


load_env_file()
APP_NAME = 'NEXO'
APP_SUBTITLE = 'Sistema de búsqueda y monitoreo'
HOST = os.getenv('NEXO_HOST', '127.0.0.1')
PORT = int(os.getenv('NEXO_PORT', '8080'))
DEMO_DATE = '2026-09-23'
DATA_DIR = BASE_DIR / 'data'
# Token público de Mapbox (pk.*): viaja al navegador para descargar el mapa base.
# Va en el archivo .env (ver .env.example), no en el código: GitHub bloquea los tokens.
MAPBOX_TOKEN = os.getenv('NEXO_MAPBOX_TOKEN', '')

VOICE_MODEL = os.getenv('VOICE_MODEL', 'base')
# Windows sin modo desarrollador no crea enlaces simbólicos: la caché de Hugging Face funciona
# igual (copia los archivos), así que su advertencia sólo confunde en la consola.
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
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
# El clip de evidencia (video, audio y fotos) abarca estos segundos antes y después del
# instante en que se dijo la frase de auxilio: lo justo para que una persona entienda el contexto.
EVIDENCE_PRE_SECONDS = int(os.getenv('NEXO_EVIDENCE_PRE_SECONDS', '5'))
EVIDENCE_POST_SECONDS = int(os.getenv('NEXO_EVIDENCE_POST_SECONDS', '5'))
# Ring buffer: pre-roll + window + post-roll, plus room for a slow transcription. Nothing
# older is kept.
AUDIO_RING_SECONDS = EVIDENCE_PRE_SECONDS + AUDIO_WINDOW_SECONDS + EVIDENCE_POST_SECONDS + 30
DEFAULT_CAMERA_ID = os.getenv('NEXO_CAMERA', 'CAM-008')
SECOND_CAMERA_ID = os.getenv('NEXO_CAMERA_2', 'CAM-007')
# Celular enlazado con Enlace Móvil de Windows (cámara conectada).
THIRD_CAMERA_ID = os.getenv('NEXO_CAMERA_3', 'CAM-004')


def parse_latlng(value):
    """'25.6775,-100.2597' -> (25.6775, -100.2597); None si el texto no es una coordenada válida."""
    try:
        lat, lng = (float(part) for part in str(value).split(','))
    except (TypeError, ValueError):
        return None
    return (lat, lng) if -90 <= lat <= 90 and -180 <= lng <= 180 else None


# Dónde está físicamente cada cámara del equipo. Por defecto, tres puntos a pocos pasos entre sí
# dentro del Tec de Nuevo León, para que caminar de una a otra se vea como un trayecto en el
# mapa. Cada equipo pone aquí (o en .env) las coordenadas reales de donde instala sus cámaras.
PHYSICAL_CAMERA_POSITIONS = {
    DEFAULT_CAMERA_ID: parse_latlng(os.getenv('NEXO_CAMERA_LATLNG', '25.67750,-100.25970')),
    SECOND_CAMERA_ID: parse_latlng(os.getenv('NEXO_CAMERA_2_LATLNG', '25.67790,-100.25860')),
    THIRD_CAMERA_ID: parse_latlng(os.getenv('NEXO_CAMERA_3_LATLNG', '25.67860,-100.25730')),
}

# Base de datos local (SQLite, viene con Python): conserva todo entre reinicios sin Docker ni
# instalaciones. Vive en data/ (excluida de git). Se desactiva con NEXO_LOCAL_DB=0.
LOCAL_DB_ENABLED = os.getenv('NEXO_LOCAL_DB', '1') == '1'
LOCAL_DB_PATH = Path(os.getenv('NEXO_LOCAL_DB_PATH', str(DATA_DIR / 'nexo.db')))
LOCAL_DB_SAVE_SECONDS = float(os.getenv('NEXO_LOCAL_DB_SAVE_SECONDS', '3'))
LOCAL_DB_MAX_LOGS = 20000

# Importación de alertas de búsqueda: archivos temporales, nunca evidencia.
# Base de datos PostgreSQL (docker-compose.yml). Opcional: sin contenedor, NEXO trabaja con la base local.
DB_SYNC_ENABLED = os.getenv('NEXO_DB_SYNC', '1') == '1'
DB_SYNC_SECONDS = float(os.getenv('NEXO_DB_SYNC_SECONDS', '5'))
# Identifica de qué equipo vino cada registro de la bitácora compartida (varias personas,
# varias instancias, misma base de datos).
DEVICE_ID = os.getenv('NEXO_DEVICE_ID') or socket.gethostname()

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
# Al arrancar, los modelos facial y de voz se preparan solos en segundo plano (la primera vez se
# descargan). Así nadie tiene que ejecutar nada y todo queda listo aunque no haya cámara.
MODELS_AUTOPREPARE = os.getenv('NEXO_MODELS_AUTOPREPARE', 'true').lower() in ('true', '1', 'yes')
FACE_MIN_DET_SCORE = 0.5
# Similitud coseno entre huellas de buffalo_l. Orientativa: siempre requiere revisión humana.
FACE_MATCH_THRESHOLD = 0.45
FACE_LEVEL_MEDIUM = 0.50
FACE_LEVEL_HIGH = 0.60

# Reconocimiento en vivo: la webcam del equipo donde corre NEXO, asociada a una cámara de la red.
CAMERA_INDEX = int(os.getenv('NEXO_CAMERA_INDEX', '0'))
CAMERA_INDEX_2 = int(os.getenv('NEXO_CAMERA_INDEX_2', '1'))
CAMERA_INDEX_3 = int(os.getenv('NEXO_CAMERA_INDEX_3', '2'))
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
# Ventana de video conservada alrededor de un evento: la misma que la del audio, para que el
# clip se vea y se escuche completo. Fuera de ella el anillo se sobrescribe.
VIDEO_PRE_EVENT_SECONDS = EVIDENCE_PRE_SECONDS
VIDEO_POST_EVENT_SECONDS = EVIDENCE_POST_SECONDS
# El análisis de voz llega con algunos segundos de retraso respecto del grito: el anillo
# guarda de sobra para que el "antes" siga ahí cuando se pide.
VIDEO_RING_SECONDS = VIDEO_PRE_EVENT_SECONDS + VIDEO_POST_EVENT_SECONDS + 30
VIDEO_RING_FPS = 12
VIDEO_RING_JPEG_QUALITY = 80
# Margen al buscar el fotograma más próximo a cada instante pedido.
EVENT_FRAME_TOLERANCE_SECONDS = 1.0
# Un solo fotograma puede salir borroso o de perfil: se toman varios alrededor del evento,
# también antes de la frase, cuando la persona quizá todavía miraba a la cámara.
EVENT_FRAME_OFFSETS_SECONDS = (-2, 0, 1, 2, 4)
# Si el modelo facial no carga, la cámara sigue grabando y se reintenta cada tanto.
FACE_MODEL_RETRY_SECONDS = 60

# ------------------------------------------------ seguimiento de las personas de un evento
# Tras una posible solicitud de auxilio, las cámaras del equipo buscan por sí solas a las
# personas que se vieron en el evento durante un tiempo corto (provisional). Si una persona
# confirma el seguimiento, se amplía; si marca falso positivo, se detiene.
EVENT_TRACKING_MINUTES = int(os.getenv('NEXO_EVENT_TRACKING_MINUTES', '60'))
EVENT_TRACKING_CONFIRMED_HOURS = int(os.getenv('NEXO_EVENT_TRACKING_CONFIRMED_HOURS', '12'))
# Una reaparición por persona y cámara en cada ventana, para no llenar el trayecto de repeticiones.
TRACK_SIGHTING_COOLDOWN_SECONDS = 30

# ------------------------------------------------------- motor de búsqueda multimodal
# La hora de desaparición marca el inicio de la ventana prioritaria; nada se descarta por tiempo.
SEARCH_UNKNOWN_TIME_TOLERANCE_HOURS = 12
SEARCH_PRIORITY_WINDOW_DAYS = 7
# Distancia en el plano de demostración; la cercanía prioriza, nunca excluye.
SEARCH_NEAR_DISTANCE = 18.0
SEARCH_FAR_DISTANCE = 45.0
# Distancias reales (km) al último lugar conocido de la ficha.
SEARCH_NEAR_KM = 5.0
SEARCH_FAR_KM = 60.0
# Velocidades para juzgar si un desplazamiento es posible en el tiempo transcurrido: a pie,
# en vehículo; más rápido que eso, uno de los dos puntos probablemente es un falso positivo.
WALKING_MAX_KMH = 7.0
VEHICLE_MAX_KMH = 130.0
# Continuidad entre cámaras relacionadas: dos apariciones compatibles dentro de esta ventana.
SEARCH_ROUTE_WINDOW_MINUTES = 20
# Prioridad de revisión, no probabilidad de identidad.
CANDIDATE_PRIORITY_THRESHOLD = 0.55
CANDIDATE_MAX_RESULTS = 25

# La cámara del equipo se incorpora al monitoreo continuo por sí sola. Se puede desactivar
# (NEXO_CAMERA_AUTOSTART=false) en equipos donde la webcam se necesite para otra cosa.
CAMERA_AUTOSTART = os.getenv('NEXO_CAMERA_AUTOSTART', 'true').lower() in ('true', '1', 'yes')
CAMERA_AUTOSTART_RETRY_SECONDS = 20

# Si el análisis se queda más atrás que esto, se salta al presente en vez de arrastrar el
# retraso: es preferible perder un fragmento antiguo que escuchar siempre con demora.
AUDIO_MAX_LAG_SECONDS = 8

# Cuánto tiempo la propia cámara sigue anunciando en pantalla que acaba de conservar evidencia
# de una posible solicitud de auxilio. La detección no es una pantalla aparte: ocurre en la
# cámara y se ve en la cámara.
CAMERA_EVENT_NOTICE_SECONDS = int(os.getenv('NEXO_CAMERA_EVENT_NOTICE_SECONDS', '180'))
