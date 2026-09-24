from nicegui import ui
from components.status_badge import StatusBadge
from components.states import EmptyState
from services.cameras_service import get_camera
from services.face_engine import display_level


def Timeline(events,horizontal=False,on_review=None):
    if not events:
        EmptyState('Este caso todavía no tiene detecciones.')
        return
    with ui.element('div').classes('timeline-horizontal' if horizontal else 'w-full'):
        for event in events:
            d=event.detection
            camera=get_camera(d.camera_id)
            with ui.element('div').classes('timeline-row'):
                ui.label(str(event.order)).classes('timeline-order')
                with ui.column().classes('gap-1'):
                    ui.label(d.timestamp[11:]).classes('mono font-bold')
                    ui.label(f'{d.camera_id} · {camera.name}').classes('text-xs')
                    ui.label(f'Posible coincidencia · Similitud {display_level(d.similarity)}').classes('text-[11px] muted')
                    StatusBadge(d.status)
                    if on_review:
                        ui.button('Revisar detección',on_click=lambda did=d.id:on_review(did)).props('flat dense no-caps')
