from nicegui import ui
from services.facial_service import get_detection
from services.cameras_service import get_camera
from services.face_engine import display_level
from components.person_profile import InfoPair
from components.status_badge import StatusBadge


def DetectionDetail(detection_id):
    d=get_detection(detection_id)
    with ui.dialog() as dialog,ui.card().classes('app-dialog p-5'):
        with ui.row().classes('w-full items-center justify-between'):
            ui.label('Detalle de detección / '+d.id).classes('text-lg')
            ui.button(icon='close',on_click=dialog.close).props('flat round dense')
        ui.image(d.capture).classes('max-h-72').props('fit=contain')
        for label,value in [('Cámara',d.camera_id+' · '+get_camera(d.camera_id).name),('Fecha y hora',d.timestamp),('Similitud orientativa',display_level(d.similarity)),('Calidad',d.quality)]:
            InfoPair(label,value)
        StatusBadge(d.status)
        ui.label('Detección disponible para revisión. No constituye una identificación definitiva.').classes('notice')
    dialog.open()
