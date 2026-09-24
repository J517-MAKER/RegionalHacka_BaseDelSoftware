import os
import secrets
import asyncio
from nicegui import background_tasks
from nicegui import app,ui
import config
from config import BASE_DIR,HOST,PORT
from assets.build_demo import build_assets
from services.evidence_service import ensure_directories
from services.alert_import_service import ensure_directories as ensure_import_directories

build_assets()
ensure_directories()
ensure_import_directories()
app.add_static_files('/assets',str(BASE_DIR/'assets'))
# Original evidence is served read-only; it is never written from the browser.
app.add_media_files('/evidence/audio',str(config.EVIDENCE_AUDIO_DIR))
# Fichas importadas: vista previa y recorte temporales de la importación en curso.
app.add_static_files('/imports',str(config.IMPORT_DIR))

from pages import (monitor,cases,import_alert,case_detail,cameras,live,matches,tracking,alerts,voice,  # noqa: E402,F401
                   history,users,settings,supervision)  # noqa: E402,F401
from services.live_recognition_service import live as live_recognition, stop_all  # noqa: E402


async def expire_voice_transcripts():
    from services.voice_service import prune_voice_history
    while True:
        prune_voice_history()
        await asyncio.sleep(1)


def start_voice_retention():
    background_tasks.create(expire_voice_transcripts())


if not app.is_started:  # the interface tests re-execute this module
    app.on_startup(start_voice_retention)
    app.on_shutdown(stop_all)  # release all webcams when the server stops
    # PostgreSQL: saves cases, photos, cameras and detections; never during the interface tests.
    if config.DB_SYNC_ENABLED and 'PYTEST_CURRENT_TEST' not in os.environ:
        from services.db_sync import database  # noqa: E402
        app.on_startup(database.start)
        app.on_shutdown(database.stop)


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
