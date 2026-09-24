"""Trayecto estimado de una persona a partir de dónde la vieron las cámaras.

Une en orden cronológico los puntos donde se observó a alguien —detecciones de su ficha, o
reapariciones de una persona vista en un evento— y, entre cada par, estima el trayecto: la
distancia real, el tiempo, la velocidad que implicaría y si es posible a pie, en vehículo o no
es posible (en cuyo caso una de las dos observaciones probablemente es un falso positivo).

Es una estimación para orientar la búsqueda: el camino exacto entre dos cámaras no se
observa, y cada punto sigue pendiente de validación humana hasta que alguien lo confirme.
"""
import heapq
from dataclasses import dataclass, field
from datetime import datetime
import config
from services import store
from services.geo_service import bearing, camera_position, haversine_km, human_distance

# Estados de un punto del trayecto, del más al menos confirmado.
POINT_LABELS = {'VALIDADA': 'Validada por una persona', 'POSIBLE': 'Posible, pendiente de validación',
                'EVENTO': 'Momento del evento de auxilio', 'AVISTAMIENTO': 'Reaparición en otra cámara'}
PLAUSIBILITY_LABELS = {'MISMO_LUGAR': 'Mismo lugar', 'A_PIE': 'Posible a pie', 'VEHICULO': 'Posible en vehículo',
                       'NO_PLAUSIBLE': 'No es posible en ese tiempo', 'SIN_TIEMPO': 'Sin tiempo entre puntos'}
VALIDATED_DETECTION = ('Validada por operador',)
DISCARDED = ('Descartada',)


@dataclass
class RoutePoint:
    order: int
    camera_id: str
    camera_name: str
    lat: float
    lng: float
    first_seen: str
    last_seen: str
    status: str  # VALIDADA · POSIBLE · EVENTO · AVISTAMIENTO
    source: str  # DETECCION · CANDIDATO · EVENTO · SEGUIMIENTO
    image: str = ''
    level: str = ''
    refs: list = field(default_factory=list)
    observations: int = 1


@dataclass
class RouteLeg:
    start: int
    end: int
    distance_km: float
    minutes: float | None
    speed_kmh: float | None
    plausibility: str
    mode: str  # walking · driving · none (línea recta)
    heading: float
    via: list = field(default_factory=list)


@dataclass
class Route:
    subject_type: str  # CASO · EVENTO
    subject_id: str
    subject_label: str
    points: list = field(default_factory=list)
    legs: list = field(default_factory=list)
    reference: dict | None = None  # último lugar conocido de la ficha, o el evento
    next_cameras: list = field(default_factory=list)  # [(km, cámara)]
    warnings: list = field(default_factory=list)

    @property
    def last_point(self):
        return self.points[-1] if self.points else None

    @property
    def last_validated(self):
        return next((p for p in reversed(self.points) if p.status == 'VALIDADA'), None)

    @property
    def total_km(self):
        return round(sum(leg.distance_km for leg in self.legs), 3)

    @property
    def elapsed_minutes(self):
        if len(self.points) < 2:
            return 0.0
        return _minutes(self.points[0].first_seen, self.points[-1].last_seen) or 0.0


def _parse(moment):
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(str(moment), fmt)
        except ValueError:
            continue
    return None


def _minutes(first, second):
    a, b = _parse(first), _parse(second)
    return None if a is None or b is None else (b - a).total_seconds() / 60


def plausibility(distance_km, minutes):
    """(clave, velocidad km/h) de un desplazamiento entre dos observaciones."""
    if distance_km < .03:
        return 'MISMO_LUGAR', None
    if minutes is None or minutes <= 0:
        return ('NO_PLAUSIBLE' if distance_km > .2 else 'SIN_TIEMPO'), None
    speed = distance_km / (minutes / 60)
    if speed <= config.WALKING_MAX_KMH:
        return 'A_PIE', speed
    if speed <= config.VEHICLE_MAX_KMH:
        return 'VEHICULO', speed
    return 'NO_PLAUSIBLE', speed


def topology_path(start_id, end_id):
    """Cámaras intermedias por la red de cámaras contiguas (camino más corto en km)."""
    from services.cameras_service import get_camera
    start, end = get_camera(start_id), get_camera(end_id)
    if start is None or end is None or start_id == end_id or end_id in (start.nearby_camera_ids or []):
        return []
    graph = {}
    for camera in store.cameras:
        for other_id in camera.nearby_camera_ids or []:
            other = get_camera(other_id)
            if other is None:
                continue
            km = haversine_km(camera_position(camera), camera_position(other))
            graph.setdefault(camera.id, {})[other_id] = km
            graph.setdefault(other_id, {})[camera.id] = km
    queue, best, previous = [(0.0, start_id)], {start_id: 0.0}, {}
    while queue:
        cost, node = heapq.heappop(queue)
        if node == end_id:
            break
        if cost > best.get(node, float('inf')):
            continue
        for neighbour, km in graph.get(node, {}).items():
            total = cost + km
            if total < best.get(neighbour, float('inf')):
                best[neighbour], previous[neighbour] = total, node
                heapq.heappush(queue, (total, neighbour))
    if end_id not in previous:
        return []
    direct = haversine_km(camera_position(start), camera_position(end))
    if best[end_id] > direct * 1.6:
        return []  # el rodeo por la red no explica el trayecto: mejor no sugerirlo
    path, node = [], previous[end_id]
    while node != start_id:
        path.append(node)
        node = previous[node]
    return list(reversed(path))


def _observation(camera_id, timestamp, status, source, image='', level='', ref=''):
    return {'camera_id': camera_id, 'timestamp': timestamp, 'status': status, 'source': source,
            'image': image, 'level': level, 'ref': ref}


def build_route(subject_type, subject_id, subject_label, observations, reference=None):
    """Une las observaciones en orden; las consecutivas en la misma cámara son una sola parada."""
    from services.cameras_service import get_camera
    route = Route(subject_type, subject_id, subject_label, reference=reference)
    rank = {'VALIDADA': 0, 'EVENTO': 1, 'AVISTAMIENTO': 2, 'POSIBLE': 3}
    for item in sorted((o for o in observations if o['timestamp']), key=lambda o: o['timestamp']):
        camera = get_camera(item['camera_id'])
        if camera is None:
            continue
        last = route.points[-1] if route.points else None
        if last and last.camera_id == camera.id:
            last.last_seen = item['timestamp']
            last.observations += 1
            last.refs.append(item['ref'])
            if rank.get(item['status'], 9) < rank.get(last.status, 9):
                last.status = item['status']
            last.image = item['image'] or last.image
            continue
        lat, lng = camera_position(camera)
        route.points.append(RoutePoint(len(route.points) + 1, camera.id, camera.name, lat, lng, item['timestamp'],
                                       item['timestamp'], item['status'], item['source'], item['image'],
                                       item['level'], [item['ref']]))
    for index in range(len(route.points) - 1):
        a, b = route.points[index], route.points[index + 1]
        km = haversine_km((a.lat, a.lng), (b.lat, b.lng))
        minutes = _minutes(a.last_seen, b.first_seen)
        kind, speed = plausibility(km, minutes)
        mode = 'walking' if kind == 'A_PIE' and km <= 3 else 'driving' if kind in ('A_PIE', 'VEHICULO') else 'none'
        route.legs.append(RouteLeg(index, index + 1, round(km, 3), minutes, round(speed, 1) if speed else None,
                                   kind, mode, round(bearing((a.lat, a.lng), (b.lat, b.lng)), 1),
                                   topology_path(a.camera_id, b.camera_id)))
        if kind == 'NO_PLAUSIBLE':
            route.warnings.append(f'Del punto {a.order} ({a.camera_id}) al {b.order} ({b.camera_id}): '
                                  f'{human_distance(km)} en {_duration(minutes)}. No es posible en ese tiempo: '
                                  'una de las dos observaciones probablemente es un falso positivo.')
    route.next_cameras = next_cameras(route)
    return route


def next_cameras(route, limit=4):
    """Cámaras donde conviene seguir buscando: las contiguas a la última posición, sin repetir."""
    from services.cameras_service import get_camera
    last = route.last_point
    if last is None:
        return []
    visited = {p.camera_id for p in route.points[-3:]}
    here = (last.lat, last.lng)
    camera = get_camera(last.camera_id)
    candidates = [get_camera(cid) for cid in (camera.nearby_camera_ids or [])] if camera else []
    candidates = [c for c in candidates if c is not None and c.id not in visited]
    ranked = sorted(((haversine_km(here, camera_position(c)), c) for c in candidates), key=lambda item: item[0])
    return ranked[:limit]


def _duration(minutes):
    if minutes is None:
        return 'tiempo desconocido'
    if minutes < 1:
        return f'{minutes * 60:.0f} s'
    if minutes < 120:
        return f'{minutes:.0f} min'
    if minutes < 48 * 60:
        return f'{minutes / 60:.1f} h'
    return f'{minutes / 1440:.1f} días'


def duration_label(minutes):
    return _duration(minutes)


# ----------------------------------------------------------------------------- sujetos
def case_route(case_id):
    """Trayecto de una ficha: sus detecciones (sin las descartadas) y los candidatos vigentes."""
    from services.cases_service import get_case
    from services.face_engine import display_level
    from services.search_matching_service import get_candidates, get_profile
    case = get_case(case_id)
    if case is None:
        return None
    observations = []
    detection_ids = set()
    for detection in store.detections:
        if detection.case_id != case_id or detection.status in DISCARDED:
            continue
        detection_ids.add(detection.id)
        observations.append(_observation(
            detection.camera_id, detection.timestamp,
            'VALIDADA' if detection.status in VALIDATED_DETECTION else 'POSIBLE', 'DETECCION',
            detection.capture, display_level(detection.similarity), detection.id))
    for candidate in get_candidates(case_id):
        if candidate.detection_id in detection_ids or candidate.status in ('OPERATOR_REJECTED', 'SUPERVISOR_REJECTED'):
            continue
        observations.append(_observation(
            candidate.camera_id, candidate.timestamp,
            'VALIDADA' if candidate.status == 'SUPERVISOR_VALIDATED' else 'POSIBLE',
            'EVENTO' if candidate.linked_to_distress_event else 'CANDIDATO',
            candidate.face_image_path, candidate.signal('face').level, candidate.candidate_match_id))
    profile = get_profile(case_id)
    reference = None
    if profile and profile.last_known_lat is not None:
        reference = {'lat': profile.last_known_lat, 'lng': profile.last_known_lng,
                     'label': f'Último lugar conocido: {profile.last_known_place or profile.last_known_location}'}
    else:
        from services.geo_service import resolve_place
        place = resolve_place(case.location)
        if place:
            reference = {'lat': place[0], 'lng': place[1], 'label': f'Último lugar conocido: {place[2]}'}
    name = case.person.name.replace(' (ficticia)', '').replace(' (ficticio)', '')
    return build_route('CASO', case_id, f'{case_id} · {name}', observations, reference)


def event_track_route(event_id, candidate_id):
    """Trayecto de una persona vista en un evento: el evento y sus reapariciones."""
    from services.tracking_service import get_track_sightings
    event = next((e for e in store.evidence if e.event_id == event_id), None)
    candidate = next((c for c in store.person_candidates if c.candidate_id == candidate_id), None)
    if event is None or candidate is None:
        return None
    from pathlib import Path
    image = f'/evidence/frames/{Path(candidate.face_image_path).name}' if candidate.face_image_path else ''
    observations = [_observation(event.video_camera_id or event.camera_id,
                                 event.trigger_timestamp or event.created_at, 'EVENTO', 'EVENTO', image, '',
                                 event.event_id)]
    for sighting in get_track_sightings(candidate_id):
        observations.append(_observation(sighting.camera_id, sighting.timestamp,
                                         'VALIDADA' if sighting.status == 'Validada' else 'AVISTAMIENTO',
                                         'SEGUIMIENTO', sighting.capture, sighting.level, sighting.sighting_id))
    return build_route('EVENTO', f'{event_id}:{candidate_id}', f'{candidate.person_track_id} · {event_id}',
                       observations)


def route_payload(route, color='#32788A'):
    """Lo que el mapa necesita para dibujar el trayecto (sin imágenes: viajan aparte)."""
    if route is None or not route.points:
        return None
    last = route.last_point
    return {
        'color': color,
        'points': [{'order': p.order, 'lat': p.lat, 'lng': p.lng, 'camera': p.camera_id, 'name': p.camera_name,
                    'first': p.first_seen, 'last': p.last_seen, 'status': p.status,
                    'status_label': POINT_LABELS.get(p.status, p.status), 'level': p.level,
                    'count': p.observations} for p in route.points],
        'legs': [{'from': leg.start, 'to': leg.end, 'mode': leg.mode, 'plausibility': leg.plausibility,
                  'label': PLAUSIBILITY_LABELS.get(leg.plausibility, leg.plausibility),
                  'km': leg.distance_km, 'distance': human_distance(leg.distance_km),
                  'duration': _duration(leg.minutes), 'heading': leg.heading,
                  'possible': route.points[leg.end].status != 'VALIDADA'
                  or route.points[leg.start].status != 'VALIDADA'} for leg in route.legs],
        'last': {'lat': last.lat, 'lng': last.lng, 'camera': last.camera_id, 'name': last.camera_name,
                 'time': last.last_seen, 'status': last.status},
        'reference': route.reference,
    }
