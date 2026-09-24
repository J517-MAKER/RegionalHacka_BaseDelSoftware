from datetime import datetime
# pyrefly: ignore [missing-import]
from nicegui import ui
from components.layout import PageLayout,Panel
from components.map_view import MapView
from components.timeline import Timeline
from components.person_profile import InfoPair
from components.status_badge import StatusBadge
from components.detection_detail import DetectionDetail
from components.states import EmptyState
from services.cases_service import get_cases,get_case
from services.tracking_service import get_tracking_history
from services.alerts_service import get_alert,get_alert_event
from services.cameras_service import get_camera,get_nearby_cameras

@ui.page('/tracking')
def tracking_page(case_id:str='BUS-2026-0184',alert_id:str='',camera_id:str=''):
    alert = get_alert(alert_id) if alert_id else None
    
    with PageLayout('/tracking','Mapa y seguimiento','Puntos de detección y relaciones cronológicas. Las conexiones no representan una trayectoria física.'):
        if alert_id and not alert:
            EmptyState('No se encontró el evento solicitado.')
            return
            
        event = get_alert_event(alert) if alert else None
        case = None
        history = []
        
        if not alert:
            cases = get_cases()
            options = {c.id: f'{c.id} · {c.person.name}' for c in cases}
            if case_id not in options and cases:
                case_id = cases[0].id
                
            ui.select(options, value=case_id if case_id in options else None, label='Seleccionar expediente', on_change=lambda e: ui.navigate.to(f'/tracking?case_id={e.value}')).props('outlined dense').classes('w-full max-w-xl')
            case = get_case(case_id)
            if case and not camera_id:
                history = get_tracking_history(case.id)
                
        cam_id = event.camera_id if event else camera_id
        selected_camera = get_camera(cam_id) if cam_id else None
        
        with ui.element('div').classes('workspace-grid'):
            with Panel('Seguimiento de evento' if alert else 'Registro espacial de detecciones','PLANO LOCAL · DEMO'):
                MapView(detections=history, selected=selected_camera.id if selected_camera else None, height=500)
                
            with Panel('Información del seguimiento'):
                with ui.column().classes('panel-body gap-1'):
                    if selected_camera:
                        StatusBadge('Seguimiento iniciado' if alert and alert.tracking_started else selected_camera.status)
                        InfoPair('Evento / cámara', f'{alert.id if alert else "Consulta"} · {selected_camera.id}')
                        InfoPair('Ubicación', selected_camera.name)
                        
                        if event:
                            InfoPair('Frase transcrita', event.transcript)
                            InfoPair('Fecha y hora', event.timestamp)
                            ui.label('Evento independiente de los casos de búsqueda. No se ha identificado a ninguna persona.').classes('notice mt-3')
                            
                        ui.label('Cámaras cercanas').classes('section-title mt-4')
                        for cam in get_nearby_cameras(selected_camera.id):
                            ui.link(f'{cam.id} · {cam.name}', f'/cameras?camera_id={cam.id}').classes('text-xs py-1')
                            
                    elif case:
                        if case.person.photos:
                            ui.image(case.person.photos[0]).classes('w-20 h-24 mb-2').props('fit=contain')
                        ui.label(case.person.name).classes('text-base font-medium')
                        InfoPair('Folio', case.id)
                        
                        valid = [t for t in history if t.detection.status != 'Descartada']
                        if valid:
                            start_time = valid[0].detection.timestamp
                            end_time = valid[-1].detection.timestamp
                            time_diff = str(datetime.fromisoformat(end_time) - datetime.fromisoformat(start_time))
                        else:
                            start_time = end_time = 'Sin detecciones'
                            time_diff = '—'
                            
                        unique_cams = len(set(t.detection.camera_id for t in history))
                        
                        for label, value in [('Inicio del seguimiento', start_time),
                                             ('Última detección', end_time),
                                             ('Tiempo entre detecciones', time_diff),
                                             ('Cámaras con detecciones', unique_cams),
                                             ('Posibles coincidencias', len(valid))]:
                            InfoPair(label, value)
                            
                        confirmed = [t for t in history if t.detection.status == 'Validada por operador']
                        InfoPair('Última validada por operador', confirmed[-1].detection.camera_id if confirmed else 'Pendiente de validación')
                        
                        ui.link('Abrir expediente →', f'/cases/{case.id}').classes('text-xs mt-4')
                        
        with Panel('Línea temporal','ORDEN CRONOLÓGICO'):
            with ui.element('div').classes('px-5 py-2'):
                if history:
                    Timeline(history, horizontal=True, on_review=DetectionDetail)
                elif event:
                    InfoPair(event.timestamp, f'{event.camera_id} · Posible solicitud de auxilio · {alert.status}')
                else:
                    EmptyState('Sin detecciones para esta vista.')
