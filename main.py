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


@ui.page('/')
def index():
    # Each role lands on its own console instead of always on the operator's monitor.
    from services.users_service import home_route
    ui.navigate.to(home_route())


if __name__ in {'__main__','__mp_main__'}:
    ui.run(host=HOST,port=PORT,title='NEXO · Búsqueda y monitoreo',language='es',
           reload=False,show=os.getenv('NEXO_SHOW','1')=='1',
           storage_secret=os.getenv('NEXO_STORAGE_SECRET') or secrets.token_hex(32),
           favicon='assets/icons/nexo.svg')
