import os
import logging
import secrets
import asyncio
from nicegui import background_tasks
from nicegui import app,ui
import config
from config import BASE_DIR,HOST,PORT

# Sin esto, los avisos de conexión de services/db_sync.py (nivel INFO) quedan
# ocultos: Python no los muestra en consola a menos que se pida explícitamente.
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
from assets.build_demo import build_assets
from services.evidence_service import ensure_directories
from services.event_frames_service import ensure_directories as ensure_frame_directories
from services.alert_import_service import ensure_directories as ensure_import_directories

build_assets()
ensure_directories()
ensure_frame_directories()
ensure_import_directories()
app.add_static_files('/assets',str(BASE_DIR/'assets'))
# Original evidence is served read-only; it is never written from the browser.
app.add_media_files('/evidence/audio',str(config.EVIDENCE_AUDIO_DIR))
# El fragmento de video y los fotogramas del evento, para que otra persona pueda revisarlos.
app.add_media_files('/evidence/video',str(config.EVIDENCE_VIDEO_DIR))
app.add_static_files('/evidence/frames',str(config.EVIDENCE_DIR/'frames'))
# Fichas importadas: vista previa y recorte temporales de la importación en curso.
app.add_static_files('/imports',str(config.IMPORT_DIR))

from pages import (monitor,cases,import_alert,case_detail,cameras,live,matches,tracking,alerts,voice,  # noqa: E402,F401
                   history,users,settings,supervision)  # noqa: E402,F401
from services.live_recognition_service import stop_all as stop_live_cameras  # noqa: E402


async def expire_voice_transcripts():
    from services.voice_service import prune_voice_history
    while True:
        prune_voice_history()
        await asyncio.sleep(1)


def start_voice_retention():
    background_tasks.create(expire_voice_transcripts())


def start_database_sync():
    """Conecta con la base de datos compartida por el equipo (services/db_sync.py). Si el
    contenedor de PostgreSQL no está disponible, NEXO sigue funcionando sólo en memoria."""
    if not config.DB_SYNC_ENABLED:
        return
    from services.db_sync import database
    database.start()


def stop_database_sync():
    from services.db_sync import database
    database.stop()


def start_continuous_monitoring():
    """Enciende la cámara del equipo y el micrófono sin que nadie tenga que pulsar
    INICIAR/REANUDAR: así el llamado de auxilio detectado por voz queda vinculado a la
    cámara en vivo desde que arranca el servidor (services/camera_monitor_service.py crea el
    fragmento de video alrededor de cada evento). Se desactiva con NEXO_CAMERA_AUTOSTART=false
    y nunca corre bajo las pruebas."""
    from services.camera_monitor_service import monitor
    monitor.start()


def stop_continuous_monitoring():
    from services.camera_monitor_service import monitor
    monitor.stop()
    monitor.audio_session().stop()


if not app.is_started:  # the interface tests re-execute this module
    app.on_startup(start_voice_retention)
    app.on_startup(start_database_sync)
    app.on_startup(start_continuous_monitoring)
    app.on_shutdown(stop_live_cameras)  # libera las dos cámaras al detener el servidor
    app.on_shutdown(stop_continuous_monitoring)
    app.on_shutdown(stop_database_sync)


@ui.page('/')
def index():
    # Each role lands on its own console instead of always on the operator's monitor.
    from services.users_service import home_route
    ui.navigate.to(home_route())


def port_in_use(host, port):
    """True when another program (usually an earlier NEXO still running) already listens there."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(.5)
        return probe.connect_ex((host, port)) == 0


if __name__ in {'__main__','__mp_main__'}:
    # The interface tests also run this module, without opening the port.
    if __name__ == '__main__' and 'PYTEST_CURRENT_TEST' not in os.environ and port_in_use(HOST, PORT):
        raise SystemExit(f'El puerto {PORT} ya está en uso: probablemente NEXO sigue abierto en otra terminal.\n'
                         f'Ciérralo (Ctrl+C en esa terminal) o abre http://{HOST}:{PORT}, '
                         f'o usa otro puerto: $env:NEXO_PORT="8081"; python main.py')
    ui.run(host=HOST,port=PORT,title='NEXO · Búsqueda y monitoreo',language='es',
           reload=False,show=os.getenv('NEXO_SHOW','1')=='1',
           storage_secret=os.getenv('NEXO_STORAGE_SECRET') or secrets.token_hex(32),
           favicon='assets/icons/nexo.svg')
