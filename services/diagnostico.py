"""Diagnóstico del equipo: qué tiene NEXO para funcionar y qué le falta.

    python -m services.diagnostico

No graba, no descarga modelos y no modifica nada: sólo mira. (Sin pygrabber, para contar las
cámaras abre cada una un instante y la suelta.) Cada línea dice OK, AVISO (funciona con
limitaciones) o FALTA (y cómo resolverlo).
"""
import importlib.metadata
import importlib.util
import os
import platform
import socket
import sys
from pathlib import Path

os.environ.setdefault('OPENCV_LOG_LEVEL', 'ERROR')  # antes de importar cv2: sin avisos internos al contar cámaras
import config  # noqa: E402

PACKAGES = [('nicegui', 'Interfaz web'), ('numpy', 'Cálculo'), ('opencv-python', 'Cámaras e imágenes'),
            ('av', 'Clips de video con audio (MP4)'), ('sounddevice', 'Micrófono'),
            ('faster-whisper', 'Transcripción de voz'), ('insightface', 'Reconocimiento facial'),
            ('onnxruntime', 'Motor de los modelos'), ('pymupdf', 'Fichas en PDF'),
            ('rapidocr-onnxruntime', 'Lectura de fichas (OCR)'), ('psycopg', 'PostgreSQL (opcional)'),
            ('pgvector', 'Búsqueda vectorial en PostgreSQL (opcional)'), ('pygrabber', 'Nombres de cámaras')]
OPTIONAL = {'psycopg', 'pgvector', 'pygrabber'}


def line(state, label, detail=''):
    print(f'  [{state:<5}] {label}' + (f' — {detail}' if detail else ''))


def section(title):
    print(f'\n{title}')


def check_packages():
    section('Paquetes de Python')
    missing = []
    for name, purpose in PACKAGES:
        try:
            version = importlib.metadata.version(name)
            line('OK', f'{name} {version}', purpose)
        except importlib.metadata.PackageNotFoundError:
            state = 'AVISO' if name in OPTIONAL else 'FALTA'
            line(state, name, f'{purpose}. Instala con: python -m pip install -r requirements.txt')
            missing.append(name)
    return missing


def check_devices():
    section('Cámaras y micrófono de este equipo')
    try:
        from services.live_recognition_service import KIND_LABELS, list_video_devices
        devices = list_video_devices()
        if not devices:
            line('FALTA', 'Cámaras', 'No se detectó ninguna. Conecta una webcam o revisa los permisos de Windows.')
        for device in devices:
            line('OK', f'{KIND_LABELS.get(device["kind"], device["kind"])}: {device["name"]}',
                 f'dispositivo {device["index"]}')
    except Exception as error:
        line('AVISO', 'Cámaras', f'no se pudieron listar: {error}')
    try:
        import sounddevice as sd
        device = sd.query_devices(kind='input')
        line('OK', f'Micrófono: {device["name"]}')
    except Exception as error:
        line('FALTA', 'Micrófono', f'no disponible ({error}). Revisa Configuración > Privacidad > Micrófono.')


def check_models():
    section('Modelos (se descargan una sola vez)')
    from services import face_engine
    if not face_engine.installed():
        line('FALTA', 'Modelo facial', 'InsightFace no está instalado.')
    elif face_engine.model_downloaded():
        line('OK', f'Modelo facial {config.FACE_MODEL}', str(face_engine.model_dir()))
    else:
        line('AVISO', f'Modelo facial {config.FACE_MODEL}',
             'no descargado (~330 MB). Ejecuta: python -m services.face_engine. Sin él la cámara graba '
             'igual, pero no reconoce rostros.')
    cache = Path(os.getenv('HF_HOME', Path.home() / '.cache' / 'huggingface')) / 'hub'
    whisper = list(cache.glob(f'models--Systran--faster-whisper-{config.VOICE_MODEL}')) if cache.exists() else []
    if whisper:
        line('OK', f'Modelo de voz faster-whisper «{config.VOICE_MODEL}»', str(whisper[0]))
    else:
        line('AVISO', f'Modelo de voz faster-whisper «{config.VOICE_MODEL}»',
             'se descargará solo la primera vez que el micrófono escuche (necesita Internet).')


def check_storage():
    section('Datos y evidencia')
    from services.local_db import database
    if not config.LOCAL_DB_ENABLED:
        line('AVISO', 'Base local', 'desactivada (NEXO_LOCAL_DB=0): lo registrado se pierde al reiniciar.')
    elif database.path.exists():
        summary = database.summary()
        detail = ', '.join(f'{name} {count}' for name, count in sorted(summary.items()))
        line('OK', f'Base local SQLite: {database.path}', detail or 'vacía')
    else:
        line('OK', f'Base local SQLite: {database.path}', 'se creará al iniciar NEXO (no requiere instalar nada)')
    for label, directory in (('Audio', config.EVIDENCE_AUDIO_DIR), ('Video', config.EVIDENCE_VIDEO_DIR),
                             ('Fotos', config.EVIDENCE_DIR / 'frames')):
        count = len([p for p in directory.glob('*') if p.is_file()]) if directory.exists() else 0
        line('OK', f'Evidencia · {label}', f'{count} archivo(s) en {directory}')
    from services.db_service import _host_port, driver_installed
    host, port = _host_port()
    try:
        socket.create_connection((host, port), timeout=.5).close()
        reachable = True
    except OSError:
        reachable = False
    if not config.DB_SYNC_ENABLED:
        line('AVISO', 'PostgreSQL compartido', 'sincronización desactivada (NEXO_DB_SYNC=0).')
    elif reachable and driver_installed():
        line('OK', f'PostgreSQL compartido en {host}:{port}', 'NEXO sincroniza casos, detecciones y bitácora.')
    else:
        line('AVISO', f'PostgreSQL compartido en {host}:{port}',
             'no responde. Es opcional: NEXO funciona con su base local. Para compartir con el equipo: '
             'docker compose up -d postgres_db (o DATABASE_URL apuntando a otra máquina).')


def check_configuration():
    section('Configuración')
    token = config.MAPBOX_TOKEN.strip()
    if token.startswith('pk.') and len(token) > 20:
        line('OK', 'Token de Mapbox', 'mapa blanco de México con calles y trayectos por calles.')
    else:
        line('AVISO', 'Token de Mapbox', 'no configurado en .env: el mapa usa teselas libres (CARTO) y los '
                                          'trayectos se dibujan en línea recta.')
    line('OK' if config.CAMERA_AUTOSTART else 'AVISO', 'Monitoreo continuo',
         'cámaras y micrófono se encienden solos al iniciar NEXO' if config.CAMERA_AUTOSTART
         else 'desactivado (NEXO_CAMERA_AUTOSTART=false)')
    line('OK', 'Clip de evidencia', f'{config.EVIDENCE_PRE_SECONDS} s antes y {config.EVIDENCE_POST_SECONDS} s '
                                    'después de la frase de auxilio (video con audio, WAV y fotos)')
    for camera_id, position in config.PHYSICAL_CAMERA_POSITIONS.items():
        line('OK' if position else 'AVISO', f'Ubicación de {camera_id}',
             f'{position[0]:.5f}, {position[1]:.5f}' if position else 'coordenada inválida en .env')


def main():
    print(f'NEXO · diagnóstico del equipo {config.DEVICE_ID}')
    print(f'Python {platform.python_version()} · {sys.executable}')
    if sys.prefix == sys.base_prefix:
        line('AVISO', 'Entorno virtual', 'no estás dentro de .venv; usa .\\.venv\\Scripts\\python.exe')
    missing = check_packages()
    check_devices()
    check_models()
    check_storage()
    check_configuration()
    required = [name for name in missing if name not in OPTIONAL]
    print('\nResultado: ' + ('todo lo necesario está instalado.' if not required
                             else f'faltan paquetes: {", ".join(required)}.'))
    return 1 if required else 0


if __name__ == '__main__':
    raise SystemExit(main())
