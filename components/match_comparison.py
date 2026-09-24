from nicegui import ui
from components.layout import notify_action
from components.person_profile import InfoPair
from components.status_badge import StatusBadge
from services.cases_service import get_case
from services.cameras_service import get_camera
from services.facial_service import get_detection,validate_match,reject_match,request_review
from services.face_engine import display_level
from services.users_service import can


def MatchComparison(match,on_change=None):
    d=get_detection(match.detection_id)
    case=get_case(d.case_id)
    camera=get_camera(d.camera_id)
    with ui.row().classes('items-center justify-between w-full mb-3'):
        with ui.column().classes('gap-1'):
            ui.label(case.person.name).classes('text-lg font-medium')
            ui.label(f'{match.id} / {case.id}').classes('mono muted')
        StatusBadge(match.status)
    with ui.element('div').classes('comparison-images w-full'):
        for label,source in [('Fotografía de referencia · demo',case.person.photos[0] if case.person.photos else '/assets/demo/person-1.svg'),('Captura de cámara · demo',d.capture)]:
            with ui.column().classes('gap-0'):
                ui.label(label).classes('comparison-label')
                ui.image(source).props('fit=contain')
    with ui.element('div').classes('field-grid my-3'):
        for label,value in [('Cámara / ubicación',f'{camera.id} · {camera.name}'),('Fecha y hora',d.timestamp),
                             ('Nivel de similitud',display_level(d.similarity)),('Calidad de imagen',d.quality)]:
            InfoPair(label,value)
    ui.label('El nivel de similitud es una referencia del sistema y no constituye una identificación definitiva.').classes('notice')
    # The operator reviews at first level and may escalate; the supervisor only resolves what
    # was escalated to them, and cannot escalate it back. An administrator just reads.
    if can('matches.review'):
        # El operador nunca valida solo: descarta lo que no procede, o lo escala para que
        # un supervisor resuelva. Validar es una decisión de segundo nivel.
        actions=[('Descartar',reject_match,'Coincidencia descartada.'),
                 ('Solicitar revisión',request_review,'Evento enviado a revisión.')]
    elif can('matches.supervise') and match.status=='En revisión':
        actions=[('Resolver: validar coincidencia',validate_match,'Coincidencia validada en supervisión.'),
                 ('Resolver: descartar',reject_match,'Coincidencia descartada en supervisión.')]
    else:
        actions=[]
    with ui.row().classes('gap-2 mt-4 flex-wrap'):
        for label,action,success in actions:
            ui.button(label,on_click=lambda a=action,s=success:notify_action(lambda:a(match.id),s,on_change)).props('no-caps '+('outline' if action!=validate_match else 'unelevated'))
        ui.button('Ver trayectoria',on_click=lambda:ui.navigate.to(f'/tracking?case_id={case.id}')).props('flat no-caps')
    if not actions:
        ui.label('Consulta. La validación corresponde al operador y la resolución de lo escalado al supervisor.').classes('text-xs muted mt-2')
    if match.reviewed_by:
        ui.label(f'Revisión registrada: {match.reviewed_by} · {match.reviewed_at}').classes('text-xs muted mt-3')
