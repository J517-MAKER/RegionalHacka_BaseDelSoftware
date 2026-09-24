"""Mapa y seguimiento: dónde se vio a una persona, por dónde pudo moverse y dónde se vio al final.

El sujeto puede ser una ficha de búsqueda (sus detecciones en las cámaras) o una persona vista
en un evento de auxilio (sus reapariciones en las demás cámaras del equipo). El mapa une los
puntos en orden, estima cada tramo y marca la última posición conocida. Se actualiza solo: si
la persona camina de la cámara A a la B, el trayecto crece mientras se mira.
"""
from nicegui import ui
from components.layout import PageLayout, Panel, guard_page
from components.map_view import MapView, update_route
from components.person_profile import InfoPair
from components.states import EmptyState
from components.timeline import Timeline
from components.detection_detail import DetectionDetail
from services.alerts_service import get_alert, get_alert_event
from services.cameras_service import get_camera, get_nearby_cameras
from services.cases_service import get_case, get_cases
from services.geo_service import human_distance
from services.route_service import (PLAUSIBILITY_LABELS, POINT_LABELS, case_route, duration_label,
                                    event_track_route)
from services.tracking_service import get_track_sightings, get_tracking_history
from services import store

REFRESH_SECONDS = 5
STATUS_BADGES = {'VALIDADA': 'green', 'POSIBLE': 'amber', 'EVENTO': 'red', 'AVISTAMIENTO': 'blue'}


def clean(name):
    return (name or '').replace(' (ficticia)', '').replace(' (ficticio)', '')


def subject_options():
    """Fichas y personas de eventos con reapariciones, en un solo selector."""
    options = {f'case:{c.id}': f'Ficha · {c.id} · {clean(c.person.name)}' for c in get_cases()}
    for candidate in store.person_candidates:
        if get_track_sightings(candidate.candidate_id):
            options[f'track:{candidate.event_id}:{candidate.candidate_id}'] = \
                f'Evento · {candidate.event_id} · {candidate.person_track_id}'
    return options


def target_url(key):
    kind, _, rest = key.partition(':')
    if kind == 'track':
        event_id, _, candidate_id = rest.partition(':')
        return f'/tracking?event_id={event_id}&track={candidate_id}'
    return f'/tracking?case_id={rest}'


def event_tracks(event_id):
    return [c for c in store.person_candidates if c.event_id == event_id]


@ui.page('/tracking')
def tracking_page(case_id: str = 'BUS-2026-0184', alert_id: str = '', camera_id: str = '',
                  event_id: str = '', track: str = ''):
    if not guard_page('/tracking', 'tracking.view'):
        return
    alert = get_alert(alert_id) if alert_id else None

    with PageLayout('/tracking', 'Mapa y seguimiento',
                    'Dónde se vio a la persona, el trayecto estimado entre cámaras y su última posición '
                    'conocida. Cada punto requiere validación humana.'):
        if (alert_id and not alert) or (event_id and not any(e.event_id == event_id for e in store.evidence)):
            EmptyState('No se encontró el evento solicitado.')
            return

        # ── Sujeto del seguimiento ──────────────────────────────────────────────────────
        if event_id and not track:
            tracks = [c for c in event_tracks(event_id) if c.face_embedding]
            track = next((c.candidate_id for c in tracks if get_track_sightings(c.candidate_id)),
                         tracks[0].candidate_id if tracks else '')
        options = subject_options()
        key = None
        if event_id and track:
            key = f'track:{event_id}:{track}'
            candidate = next((c for c in store.person_candidates if c.candidate_id == track), None)
            if key not in options and candidate:
                options[key] = f'Evento · {event_id} · {candidate.person_track_id}'
        elif not event_id:
            if f'case:{case_id}' not in options and get_cases():
                case_id = get_cases()[0].id
            key = f'case:{case_id}'
        if not alert:
            ui.select(options, value=key if key in options else None, label='Persona en seguimiento',
                      on_change=lambda e: ui.navigate.to(target_url(e.value))) \
                .props('outlined dense').classes('w-full max-w-xl')
        # Un evento sin personas con rostro no se sustituye por otra ficha: se dice qué falta.
        untracked_event = bool(event_id and not track and not alert)
        if untracked_event:
            with ui.row().classes('page-note items-start'):
                ui.icon('info_outline', size='16px')
                ui.label(f'{event_id} todavía no tiene una persona con rostro para seguir entre cámaras: '
                         'falta el modelo facial, nadie quedó de frente a la cámara o el video está '
                         'pendiente. Revisa su evidencia.').classes('flex-1')
                ui.link('Ver evidencia →', f'/alerts?event_id={event_id}').classes('text-xs no-underline')

        def current_route():
            if alert or untracked_event:
                return None
            if event_id and track:
                return event_track_route(event_id, track)
            return case_route(case_id)

        route = current_route()
        event = get_alert_event(alert) if alert else None
        cam_id = event.camera_id if event else camera_id
        selected_camera = get_camera(cam_id) if cam_id else None

        with ui.element('div').classes('workspace-grid'):
            with Panel('Trayecto estimado' if route else 'Seguimiento de evento',
                       'MAPA · ÚLTIMA POSICIÓN Y RECORRIDO'):
                history = get_tracking_history(case_id) if not (event_id or alert) else []
                the_map = MapView(detections=history, selected=selected_camera.id if selected_camera else None,
                                  height=540, route=route if route and route.points else None)

            with Panel('Última posición conocida', 'SE ACTUALIZA SOLA'):
                @ui.refreshable
                def side():
                    current = current_route()
                    with ui.column().classes('panel-body gap-2 w-full'):
                        if alert:
                            AlertSummary(alert, event, selected_camera)
                        elif current is None or not current.points:
                            EmptyState('Todavía no hay observaciones para trazar un trayecto.')
                            if current is not None and current.reference:
                                InfoPair('Ficha', current.reference['label'])
                        else:
                            LastPosition(current)
                            RouteSummary(current)
                side()

        with Panel('Tramos del trayecto', 'ORDEN CRONOLÓGICO · DISTANCIA · TIEMPO · POSIBILIDAD'):
            @ui.refreshable
            def legs():
                current = current_route()
                with ui.column().classes('px-5 py-3 w-full gap-0'):
                    if alert:
                        InfoPair(event.timestamp, f'{event.camera_id} · Posible solicitud de auxilio · {alert.status}')
                    elif current is None or len(current.points) < 2:
                        EmptyState('Con una sola observación no hay tramos: la última posición es ese punto.')
                    else:
                        Legs(current)
            legs()

        if not alert and not event_id:
            with Panel('Línea temporal', 'DETECCIONES DE LA FICHA'):
                @ui.refreshable
                def timeline():
                    with ui.element('div').classes('px-5 py-2'):
                        events = get_tracking_history(case_id)
                        if events:
                            Timeline(events, horizontal=True, on_review=DetectionDetail)
                        else:
                            EmptyState('Sin detecciones para esta ficha.')
                timeline()
        else:
            timeline = None

        def refresh():
            if alert:
                return
            if update_route(the_map, current_route()):
                side.refresh()
                legs.refresh()
                if timeline:
                    timeline.refresh()
        ui.timer(REFRESH_SECONDS, refresh)


def AlertSummary(alert, event, camera):
    InfoPair('Evento / cámara', f'{alert.id} · {camera.id if camera else "—"}')
    if camera:
        InfoPair('Ubicación', camera.name)
    InfoPair('Frase transcrita', event.transcript)
    InfoPair('Fecha y hora', event.timestamp)
    ui.label('Evento independiente de los casos de búsqueda. No se ha identificado a ninguna persona.') \
        .classes('notice mt-3')
    if camera:
        ui.label('Cámaras cercanas').classes('section-title mt-4')
        for cam in get_nearby_cameras(camera.id):
            ui.link(f'{cam.id} · {cam.name}', f'/cameras?camera_id={cam.id}').classes('text-xs py-1')


def LastPosition(route):
    last = route.last_point
    with ui.element('div').classes('last-position-card'):
        with ui.row().classes('items-center justify-between w-full'):
            ui.label('ÚLTIMA POSICIÓN CONOCIDA').classes('eyebrow')
            with ui.element('span').classes(f'badge {STATUS_BADGES.get(last.status, "")}'):
                ui.element('span').classes('status-dot')
                ui.label(POINT_LABELS.get(last.status, last.status))
        with ui.row().classes('items-center gap-3 mt-2 no-wrap'):
            if last.image:
                ui.image(last.image).classes('w-16 h-20 rounded shrink-0').props('fit=cover')
            with ui.column().classes('gap-0'):
                ui.label(f'{last.camera_id} · {last.camera_name}').classes('text-base font-medium').mark('last-camera')
                ui.label(f'Vista a las {last.last_seen[11:]} del {last.last_seen[:10]}').classes('text-xs')
                ui.label(f'{last.lat:.5f}, {last.lng:.5f}').classes('mono muted')
                if last.observations > 1:
                    ui.label(f'{last.observations} observaciones en este punto (desde {last.first_seen[11:]})') \
                        .classes('text-[11px] muted')
    validated = route.last_validated
    if validated and validated is not last:
        InfoPair('Última validada por una persona', f'{validated.camera_id} · {validated.last_seen}')
    elif not validated:
        InfoPair('Última validada por una persona', 'Ninguna todavía: todo el trayecto es posible, no confirmado')


def RouteSummary(route):
    InfoPair('Persona en seguimiento', route.subject_label)
    InfoPair('Puntos observados', f'{len(route.points)} cámara(s)')
    if route.legs:
        InfoPair('Recorrido estimado', f'{human_distance(route.total_km)} en {duration_label(route.elapsed_minutes)}')
    if route.reference:
        InfoPair('Referencia de la ficha', route.reference['label'])
    for warning in route.warnings:
        ui.label(warning).classes('notice')
    if route.next_cameras:
        ui.label('DÓNDE SEGUIR BUSCANDO').classes('eyebrow mt-2')
        for km, camera in route.next_cameras:
            status = 'desconectada' if camera.status == 'Desconectada' else 'en línea'
            ui.link(f'{camera.id} · {camera.name} · a {human_distance(km)} ({status})',
                    f'/cameras?camera_id={camera.id}').classes('text-xs py-1 no-underline')
        ui.label('Cámaras contiguas a la última posición: el siguiente lugar lógico donde revisar.') \
            .classes('text-[10px] muted')


def Legs(route):
    for leg in route.legs:
        a, b = route.points[leg.start], route.points[leg.end]
        bad = leg.plausibility == 'NO_PLAUSIBLE'
        with ui.element('div').classes('route-leg'):
            ui.label(str(b.order)).classes('route-order')
            with ui.column().classes('gap-0 min-w-0'):
                ui.label(f'{a.camera_id} {a.camera_name} → {b.camera_id} {b.camera_name}').classes('text-xs font-medium')
                detail = f'{a.last_seen[11:]} → {b.first_seen[11:]} · {human_distance(leg.distance_km)} en ' \
                         f'{duration_label(leg.minutes)}'
                if leg.speed_kmh:
                    detail += f' · {leg.speed_kmh:.1f} km/h'
                ui.label(detail).classes('text-[11px] muted')
                if leg.via:
                    ui.label('Posible paso por ' + ', '.join(leg.via)).classes('text-[10px] muted')
            with ui.element('span').classes('badge ' + ('red' if bad else 'green' if leg.plausibility == 'A_PIE'
                                                        else 'blue')):
                ui.label(PLAUSIBILITY_LABELS.get(leg.plausibility, leg.plausibility))
