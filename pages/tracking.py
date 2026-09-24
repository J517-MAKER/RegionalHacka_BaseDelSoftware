from datetime import datetime
# pyrefly: ignore [missing-import]
from nicegui import ui
from components.layout import PageLayout, Panel, guard_page
from components.map_view import MapView
from components.timeline import Timeline
from components.person_profile import InfoPair
from components.status_badge import StatusBadge
from components.detection_detail import DetectionDetail
from components.states import EmptyState
from services.cases_service import get_cases, get_case
from services.tracking_service import get_tracking_history
from services.alerts_service import get_alert, get_alert_event
from services.cameras_service import get_camera, get_nearby_cameras


@ui.page('/tracking')
def tracking_page(case_id: str = 'BUS-2026-0184', alert_id: str = '', camera_id: str = ''):
    if not guard_page('/tracking', 'tracking.view'):
        return
    alert = get_alert(alert_id) if alert_id else None

    with PageLayout('/tracking', 'Mapa y seguimiento',
                    'Puntos de detección y relaciones cronológicas. Las conexiones no representan una trayectoria física.'):

        # ── Inject vibrant tracking-specific styles ─────────────────────
        ui.add_css("""
        .tracking-info-panel {
            background: linear-gradient(180deg, rgba(15,23,42,0.03) 0%, transparent 100%);
        }
        .tracking-stat-row {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 12px;
            border-radius: 10px;
            transition: all 0.25s ease;
        }
        .tracking-stat-row:hover {
            background: rgba(0,240,255,0.04);
        }
        .tracking-stat-icon {
            width: 36px; height: 36px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 16px;
            flex-shrink: 0;
        }
        .tracking-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.3px;
        }
        .tracking-badge-active {
            background: rgba(0,240,255,0.1);
            color: #00F0FF;
            border: 1px solid rgba(0,240,255,0.2);
        }
        .tracking-badge-alert {
            background: rgba(255,61,113,0.1);
            color: #FF3D71;
            border: 1px solid rgba(255,61,113,0.2);
        }
        .tracking-badge-warning {
            background: rgba(255,184,0,0.1);
            color: #FFB800;
            border: 1px solid rgba(255,184,0,0.2);
        }
        .tracking-nearby-card {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 14px;
            background: linear-gradient(135deg, rgba(15,23,42,0.04) 0%, rgba(30,41,59,0.02) 100%);
            border: 1px solid rgba(0,240,255,0.08);
            border-radius: 10px;
            transition: all 0.25s ease;
            text-decoration: none;
            color: inherit;
        }
        .tracking-nearby-card:hover {
            border-color: rgba(0,240,255,0.2);
            background: rgba(0,240,255,0.04);
            transform: translateX(4px);
        }
        .tracking-nearby-dot {
            width: 8px; height: 8px;
            border-radius: 50%;
            flex-shrink: 0;
        }
        .tracking-nearby-dot.online { background: #00F0FF; box-shadow: 0 0 8px rgba(0,240,255,0.5); }
        .tracking-nearby-dot.offline { background: #64748B; }
        .tracking-nearby-dot.alert { background: #FF3D71; box-shadow: 0 0 8px rgba(255,61,113,0.5); }
        .tracking-timeline-header {
            background: linear-gradient(90deg, rgba(0,240,255,0.05), transparent);
            border-bottom: 1px solid rgba(0,240,255,0.08);
            padding: 8px 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .tracking-timeline-badge {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            background: rgba(168,85,247,0.08);
            border: 1px solid rgba(168,85,247,0.15);
            border-radius: 6px;
            padding: 3px 10px;
            font-size: 10px;
            font-weight: 600;
            color: #A855F7;
            letter-spacing: 0.5px;
        }
        .tracking-person-card {
            background: linear-gradient(135deg, rgba(15,23,42,0.05) 0%, transparent 100%);
            border: 1px solid rgba(0,240,255,0.08);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 8px;
        }
        """)

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

            ui.select(options, value=case_id if case_id in options else None,
                      label='Seleccionar expediente',
                      on_change=lambda e: ui.navigate.to(f'/tracking?case_id={e.value}')).props(
                'outlined dense').classes('w-full max-w-xl')
            case = get_case(case_id)
            if case and not camera_id:
                history = get_tracking_history(case.id)

        cam_id = event.camera_id if event else camera_id
        selected_camera = get_camera(cam_id) if cam_id else None

        with ui.element('div').classes('workspace-grid'):
            with Panel('Seguimiento de evento' if alert else 'Registro espacial de detecciones',
                       'PLANO LOCAL · DEMO'):
                MapView(detections=history,
                        selected=selected_camera.id if selected_camera else None,
                        height=500)

            with Panel('Información del seguimiento'):
                with ui.column().classes('panel-body gap-1 tracking-info-panel'):
                    if selected_camera:
                        # Status badge with vibrant colors
                        status_text = ('Seguimiento iniciado' if alert and alert.tracking_started
                                       else selected_camera.status)
                        badge_class = ('tracking-badge-active' if status_text == 'En línea'
                                       else 'tracking-badge-alert' if status_text == 'Alerta'
                                       else 'tracking-badge-warning')
                        with ui.element('div').classes(f'tracking-badge {badge_class}'):
                            ui.icon('circle', size='8px')
                            ui.label(status_text)

                        InfoPair('Evento / cámara',
                                 f'{alert.id if alert else "Consulta"} · {selected_camera.id}')
                        InfoPair('Ubicación', selected_camera.name)

                        if event:
                            InfoPair('Frase transcrita', event.transcript)
                            InfoPair('Fecha y hora', event.timestamp)
                            ui.label(
                                'Evento independiente de los casos de búsqueda. '
                                'No se ha identificado a ninguna persona.'
                            ).classes('notice mt-3')

                        # Nearby cameras with vibrant cards
                        ui.label('Cámaras cercanas').classes('section-title mt-4')
                        for cam in get_nearby_cameras(selected_camera.id):
                            dot_class = ('online' if cam.status == 'En línea'
                                         else 'alert' if cam.status == 'Alerta'
                                         else 'offline')
                            with ui.link(target=f'/cameras?camera_id={cam.id}').classes(
                                    'tracking-nearby-card no-underline'):
                                ui.element('div').classes(f'tracking-nearby-dot {dot_class}')
                                with ui.column().classes('gap-0'):
                                    ui.label(cam.id).classes('text-xs font-semibold')
                                    ui.label(cam.name).classes('text-[10px] text-gray-500')

                    elif case:
                        # Person card with enhanced styling
                        with ui.element('div').classes('tracking-person-card'):
                            with ui.row().classes('items-center gap-4'):
                                if case.person.photos:
                                    ui.image(case.person.photos[0]).classes(
                                        'w-20 h-24 mb-0').props('fit=contain').style(
                                        'border-radius:10px; border:2px solid rgba(0,240,255,0.15);')
                                with ui.column().classes('gap-1'):
                                    ui.label(case.person.name).classes('text-base font-medium')
                                    with ui.element('div').classes('tracking-badge tracking-badge-active'):
                                        ui.label(case.id)

                        valid = [t for t in history if t.detection.status != 'Descartada']
                        if valid:
                            start_time = valid[0].detection.timestamp
                            end_time = valid[-1].detection.timestamp
                            time_diff = str(datetime.fromisoformat(end_time)
                                            - datetime.fromisoformat(start_time))
                        else:
                            start_time = end_time = 'Sin detecciones'
                            time_diff = '—'

                        unique_cams = len(set(t.detection.camera_id for t in history))

                        for label, value in [
                            ('Inicio del seguimiento', start_time),
                            ('Última detección', end_time),
                            ('Tiempo entre detecciones', time_diff),
                            ('Cámaras con detecciones', unique_cams),
                            ('Posibles coincidencias', len(valid)),
                        ]:
                            InfoPair(label, value)

                        confirmed = [t for t in history
                                     if t.detection.status == 'Validada por operador']
                        InfoPair('Última validada por operador',
                                 confirmed[-1].detection.camera_id if confirmed
                                 else 'Pendiente de validación')

                        ui.link('Abrir expediente →', f'/cases/{case.id}').classes(
                            'text-xs mt-4')

        # Timeline section with vibrant header
        with Panel('Línea temporal', 'ORDEN CRONOLÓGICO'):
            with ui.element('div').classes('tracking-timeline-header'):
                ui.element('span').classes('tracking-timeline-badge').props(
                    'innerHTML="⏱ CRONOLOGÍA"')
                total = len(history) if history else (1 if event else 0)
                ui.label(f'{total} evento{"s" if total != 1 else ""} registrado{"s" if total != 1 else ""}').classes(
                    'text-xs text-gray-500')
            with ui.element('div').classes('px-5 py-2'):
                if history:
                    Timeline(history, horizontal=True, on_review=DetectionDetail)
                elif event:
                    InfoPair(event.timestamp,
                             f'{event.camera_id} · Posible solicitud de auxilio · {alert.status}')
                else:
                    EmptyState('Sin detecciones para esta vista.')
