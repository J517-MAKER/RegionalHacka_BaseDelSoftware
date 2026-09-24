"""Motor de búsqueda multimodal: de una ficha a candidatos priorizados.

Lo que este módulo NO hace: decir que una detección es una persona. Combina señales
independientes —rostro, tiempo, lugar, rasgos visibles y continuidad de ruta— y las conserva
por separado, porque una sola cifra escondería de dónde viene la sospecha. La puntuación
combinada ordena la cola de revisión; no es la probabilidad de que la identidad sea correcta.

Importar una ficha y buscar son pasos distintos: el perfil se crea cuando un operador ya
confirmó la fotografía y corrigió el OCR. La búsqueda mira también hacia atrás, porque una
ficha registrada hoy puede corresponder a una detección de la semana pasada.

Fuentes que se comparan con una ficha: las personas vistas en eventos de auxilio, las
detecciones de las cámaras que guardaron la huella del rostro y, si la base compartida está
conectada, las capturas registradas en ella. Cuando una cámara ve a alguien en un evento, sus
rostros se comparan solos contra todas las fichas activas.
"""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import uuid4
import config
from models.candidate_match import CandidateMatch, MatchSignal
from models.search_profile import SearchProfile
from services import store
from services.users_service import require

DATE_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d', '%d/%m/%Y %H:%M', '%d/%m/%Y')


def parse_datetime(value):
    """Acepta lo que la ficha traiga. Devuelve (fecha, hora_conocida) o (None, False)."""
    text = (value or '').strip()
    if not text:
        return None, False
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed, '%H' in fmt
        except ValueError:
            continue
    match = re.search(r'(\d{4})-(\d{2})-(\d{2})', text) or re.search(r'(\d{2})/(\d{2})/(\d{4})', text)
    if match:
        try:
            parts = [int(p) for p in match.groups()]
            parsed = datetime(*parts) if parts[0] > 31 else datetime(parts[2], parts[1], parts[0])
            return parsed, False
        except ValueError:
            pass
    return None, False


# ------------------------------------------------------------------- perfil de búsqueda
def get_profile(case_id):
    return next((p for p in store.search_profiles if p.case_id == case_id), None)


def _fill_from_declared(profile, missing_date='', missing_time='', location='', age='', build='', height='',
                        hair='', marks='', clothing=''):
    """Lo que declara la ficha, tal cual: nada se completa por inferencia."""
    moment, time_known = parse_datetime(missing_date)
    if moment and not time_known and missing_time and missing_time != 'Desconocida':
        hour, _ = parse_datetime(f'{moment:%Y-%m-%d} {missing_time}')
        if hour:
            moment, time_known = hour, True
    profile.disappearance_datetime = moment.strftime('%Y-%m-%d %H:%M:%S') if moment else ''
    profile.disappearance_time_known = time_known
    profile.last_known_location = location or ''
    profile.last_known_camera_id = _camera_for_location(location)
    from services.geo_service import resolve_place
    place = resolve_place(location)
    profile.last_known_lat, profile.last_known_lng, profile.last_known_place = place if place else (None, None, '')
    profile.declared_age = '' if not age or 'Desconocid' in str(age) else str(age)
    profile.physical_description = ' · '.join(p for p in (build, height, hair) if p and 'Desconocid' not in p)
    profile.distinctive_marks = marks or ''
    profile.clothing_description = clothing or ''
    return profile


def create_search_profile(case_id, reference_photo='', face_embedding=None, actor=None,
                          face_status='PENDIENTE', face_message=''):
    """Crea el perfil a partir del caso ya revisado. Un caso tiene un único perfil vigente."""
    actor = actor or require('cases.manage')
    case = next((c for c in store.cases if c.id == case_id), None)
    if not case:
        raise ValueError('No se encontró el caso para crear el perfil de búsqueda.')
    existing = get_profile(case_id)
    profile = existing or SearchProfile('SP-' + uuid4().hex[:8].upper(), case_id, store.now(), actor)
    profile.official_folio = case.id
    profile.reference_photo = reference_photo or (case.person.photos[0] if case.person.photos else '')
    profile.face_embedding = list(face_embedding or profile.face_embedding)
    profile.face_status = face_status if face_embedding or face_status != 'PENDIENTE' else profile.face_status
    profile.face_message = face_message or profile.face_message
    profile.report_datetime = case.reported_at or ''
    person = case.person
    _fill_from_declared(profile, case.missing_date, case.missing_time, case.location, person.age, person.build,
                        person.height, person.hair, person.marks, person.clothing)
    if not existing:
        store.search_profiles.insert(0, profile)
    store.audit(actor, 'Búsqueda',
                f'Perfil de búsqueda {profile.profile_id} creado para {case_id}. '
                f'Referencia facial: {profile.face_status}.', case_id=case_id, result='PERFIL_CREADO')
    return profile


def _photos_signature(case):
    return hashlib.sha1('|'.join(str(p) for p in case.person.photos).encode()).hexdigest()


def case_face_reference(case):
    """(huella, estado, mensaje, foto) de la mejor fotografía de un caso.

    No dispara la descarga del modelo: si no está listo, el perfil queda pendiente y se
    recalcula la próxima vez que se consulte.
    """
    from services import face_engine
    if not case.person.photos:
        return [], 'SIN_FOTOGRAFIA', 'El caso no tiene fotografías de referencia.', ''
    if not face_engine.ready():
        return [], 'PENDIENTE_MODULO_FACIAL', 'Motor facial no disponible todavía en este equipo.', case.person.photos[0]
    from services.facial_service import reference_face
    best, photo = None, case.person.photos[0]
    for source in case.person.photos:
        try:
            face = reference_face(source)
        except face_engine.FaceEngineUnavailable as error:
            return [], 'ERROR_MODULO_FACIAL', str(error), photo
        if face is not None and (best is None or face.area * face.det_score > best.area * best.det_score):
            best, photo = face, source
    if best is None:
        return [], 'SIN_ROSTRO_DETECTADO', 'Ninguna fotografía del caso tiene un rostro detectable.', photo
    return [float(v) for v in best.embedding], 'REFERENCIA_PREPARADA', 'Huella facial generada.', photo


def ensure_profile(case, actor='Sistema'):
    """Perfil vigente de un caso, creado o actualizado sólo cuando cambian sus fotografías.

    Toda ficha registrada puede compararse, no sólo las importadas: así una persona vista en
    un evento se coteja contra todas las búsquedas activas.
    """
    from services import face_engine
    profile = get_profile(case.id)
    signature = _photos_signature(case)
    if profile is not None and profile.face_embedding and profile.reference_signature in ('', signature):
        # La referencia calculada al importar la ficha (recorte confirmado por un operador) se respeta.
        profile.reference_signature = signature
        return profile
    stale = profile is None or profile.reference_signature != signature
    if not stale and not (face_engine.ready() and case.person.photos):
        return profile  # sin cambios y sin modelo con qué completarlo
    embedding, status, message, photo = case_face_reference(case)
    if profile is None:
        profile = SearchProfile('SP-' + uuid4().hex[:8].upper(), case.id, store.now(), actor)
        store.search_profiles.insert(0, profile)
    profile.official_folio, profile.reference_photo = case.id, photo
    profile.face_embedding, profile.face_status, profile.face_message = embedding, status, message
    profile.report_datetime = case.reported_at or ''
    person = case.person
    _fill_from_declared(profile, case.missing_date, case.missing_time, case.location, person.age, person.build,
                        person.height, person.hair, person.marks, person.clothing)
    profile.reference_signature = signature
    return profile


def profile_from_reference(embedding, name='', age='', missing_date='', missing_time='', location='',
                           clothing='', marks='', photo='', source='FOTOGRAFIA_AUTORIZADA'):
    """Perfil transitorio para buscar con una ficha o una fotografía autorizada sin crear un caso."""
    profile = SearchProfile('SP-TMP-' + uuid4().hex[:6].upper(), '', store.now(), 'Consulta')
    profile.official_folio, profile.reference_photo, profile.notes = name or 'Referencia sin caso', photo, source
    profile.face_embedding = [float(v) for v in embedding] if embedding is not None else []
    profile.face_status = 'REFERENCIA_PREPARADA' if profile.face_embedding else 'SIN_ROSTRO_DETECTADO'
    return _fill_from_declared(profile, missing_date, missing_time, location, age, marks=marks, clothing=clothing)


def _camera_for_location(location):
    """Cámara más cercana al último lugar conocido, cuando el nombre coincide."""
    from services.cameras_service import get_cameras
    needle = (location or '').lower()
    if not needle:
        return ''
    for camera in get_cameras():
        if camera.name.lower() in needle or needle in camera.name.lower():
            return camera.id
    return ''


# ------------------------------------------------------------------ capturas de cámara
@dataclass
class CameraCapture:
    """Un rostro que alguna cámara guardó con su huella, venga de donde venga."""
    kind: str  # EVENTO · DETECCION · CAPTURA_BD
    capture_id: str
    camera_id: str
    timestamp: str
    embedding: list
    image: str = ''
    estimated_age: int | None = None
    clothing_color: str | None = None
    event_id: str = ''
    person_candidate_id: str = ''
    detection_id: str = ''
    case_id: str = ''
    label: str = ''
    extra: dict = field(default_factory=dict)


def _frame_url(path):
    from pathlib import Path
    return f'/evidence/frames/{Path(path).name}' if path else ''


def event_capture(candidate):
    return CameraCapture('EVENTO', candidate.candidate_id, candidate.camera_id, candidate.timestamp,
                         candidate.face_embedding, _frame_url(candidate.face_image_path),
                         getattr(candidate, 'estimated_age', None), getattr(candidate, 'clothing_color', None),
                         event_id=candidate.event_id, person_candidate_id=candidate.candidate_id,
                         label=f'{candidate.person_track_id} · {candidate.event_id}')


def detection_capture(detection):
    return CameraCapture('DETECCION', detection.id, detection.camera_id, detection.timestamp,
                         detection.embedding or [], detection.capture, detection.estimated_age,
                         detection.clothing_color, detection_id=detection.id, case_id=detection.case_id,
                         label=detection.id)


def database_captures():
    """Capturas con huella guardadas en PostgreSQL, si la base compartida está conectada."""
    try:
        from services.db_sync import database
        if database.status != 'SINCRONIZADA':
            return []
        from services.db_service import listar_capturas
        return [CameraCapture('CAPTURA_BD', f'BD-{row["id"]}', row['codigo_camara'], row['fecha_hora'],
                              row['embedding'], row.get('ruta_imagen') or '', label=f'Captura BD {row["id"]}',
                              extra={'tipo_evento': row.get('tipo_evento', '')})
                for row in listar_capturas()]
    except Exception:
        return []


def camera_captures(include_database=True):
    """Todas las capturas comparables: rostros de eventos, detecciones con huella y la base compartida."""
    captures = [event_capture(c) for c in store.person_candidates if c.face_embedding]
    captures += [detection_capture(d) for d in store.detections if d.embedding]
    if include_database:
        captures += database_captures()
    return captures


# ----------------------------------------------------------------------------- señales
def _face_signal(profile, embedding):
    from services import face_engine
    if not profile.face_embedding or not embedding:
        return MatchSignal('NO_EVALUABLE', 'Sin huella facial comparable en la ficha o en la detección.')
    value = face_engine.similarity(profile.face_embedding, embedding)
    level = face_engine.level_of(value) or 'BAJA'
    return MatchSignal(level, 'Similitud facial orientativa frente al modelo de referencia.',
                       round(float(value), 3))


def _face_signal_from_similarity(percent):
    """Detecciones ya almacenadas guardan un porcentaje, no la huella completa."""
    if percent is None:
        return MatchSignal('NO_EVALUABLE', 'La detección almacenada no conserva una medida de similitud.')
    value = percent / 100
    level = 'ALTA' if value >= config.FACE_LEVEL_HIGH else 'MEDIA' if value >= config.FACE_LEVEL_MEDIUM \
        else 'BAJA' if value >= config.FACE_MATCH_THRESHOLD else 'BAJA'
    return MatchSignal(level, 'Similitud registrada por el módulo facial sobre una detección previa.',
                       round(value, 3))


def _temporal_signal(profile, moment):
    """Una detección anterior a la desaparición no se descarta: se marca fuera del rango."""
    reference, known = parse_datetime(profile.disappearance_datetime)
    if not reference or not moment:
        return MatchSignal('NO_EVALUABLE', 'La ficha no indica fecha de desaparición comparable.'), 'SIN_REFERENCIA'
    tolerance = timedelta(hours=0 if known else config.SEARCH_UNKNOWN_TIME_TOLERANCE_HOURS)
    start = reference - tolerance
    if moment < start:
        delta = start - moment
        return (MatchSignal('BAJA', f'Anterior a la desaparición por {_human(delta)}. Se conserva para '
                                    'reconstruir la trayectoria previa.', 0.15),
                'FUERA_DEL_RANGO_PRIORITARIO')
    delta = moment - reference
    window = timedelta(days=config.SEARCH_PRIORITY_WINDOW_DAYS)
    if delta <= window:
        score = 1 - (delta / window) * .5
        note = 'Posterior a la desaparición' + (f', {_human(delta)} después.' if delta else ', en el mismo momento.')
        return MatchSignal('ALTA' if delta <= window / 2 else 'MEDIA', note, round(score, 3)), 'EN_RANGO_PRIORITARIO'
    return (MatchSignal('MEDIA', f'Posterior a la desaparición por {_human(delta)}, fuera de la ventana '
                                 'prioritaria configurada.', .35), 'EN_RANGO_PRIORITARIO')


def _human(delta):
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f'{int(delta.total_seconds() // 60)} minuto(s)'
    if hours < 48:
        return f'{hours:.0f} hora(s)'
    return f'{hours / 24:.0f} día(s)'


def _origin(profile):
    """(lat, lng, etiqueta) del último lugar conocido de la ficha, si se pudo situar."""
    from services.cameras_service import get_camera
    from services.geo_service import camera_position
    if profile.last_known_lat is not None and profile.last_known_lng is not None:
        return profile.last_known_lat, profile.last_known_lng, profile.last_known_place or profile.last_known_location
    camera = get_camera(profile.last_known_camera_id) if profile.last_known_camera_id else None
    if camera:
        lat, lng = camera_position(camera)
        return lat, lng, f'{camera.id} · {camera.name}'
    return None


def _geographic_signal(profile, camera, moment=None):
    """La cercanía prioriza; la lejanía nunca excluye.

    Con coordenadas se mide la distancia real al último lugar conocido y se contrasta con el
    tiempo transcurrido desde la desaparición: 300 km a la hora del reporte es difícil; a los
    tres días, alcanzable.
    """
    from services.geo_service import camera_position, haversine_km, human_distance
    if not camera:
        return MatchSignal('NO_EVALUABLE', 'La detección no indica cámara.')
    origin = _origin(profile)
    if not origin:
        if profile.last_known_location and profile.last_known_location.lower() in camera.name.lower():
            return MatchSignal('ALTA', f'La cámara corresponde al último lugar conocido: {camera.name}.', .9)
        return MatchSignal('NO_EVALUABLE', 'El último lugar conocido no se pudo situar en el mapa.')
    km = haversine_km(origin[:2], camera_position(camera))
    where = f'{human_distance(km)} del último lugar conocido ({origin[2]})'
    if km <= config.SEARCH_NEAR_KM:
        return MatchSignal('ALTA', f'A {where}.', round(max(.75, 1 - km / (config.SEARCH_NEAR_KM * 4)), 3))
    reference, _ = parse_datetime(profile.disappearance_datetime)
    hours = (moment - reference).total_seconds() / 3600 if reference and moment else None
    if hours is not None and hours > 0:
        speed = km / hours
        if speed <= config.WALKING_MAX_KMH:
            return MatchSignal('ALTA', f'A {where}: alcanzable a pie en el tiempo transcurrido.', .8)
        if speed <= config.VEHICLE_MAX_KMH:
            return MatchSignal('MEDIA', f'A {where}: alcanzable en vehículo en el tiempo transcurrido.', .55)
        return MatchSignal('BAJA', f'A {where}: difícil de alcanzar en el tiempo transcurrido. No se descarta.', .1)
    if km <= config.SEARCH_FAR_KM:
        return MatchSignal('MEDIA', f'A {where}, en el área ampliada.', round(1 - km / (config.SEARCH_FAR_KM * 2), 3))
    return MatchSignal('BAJA', f'A {where}. No se descarta: la ubicación prioriza, no excluye.', .1)


def _appearance_signal(profile, capture, moment=None):
    """Rasgos visibles: el color de la ropa superior y la edad aparente, frente a la ficha.

    Sólo compara lo que la ficha declara y lo que la cámara estimó; nunca descarta. Sin
    estimaciones de la captura, queda como antes: la comparación visual de apariencia (Re-ID)
    sigue pendiente de integración.
    """
    from services import person_reid_service
    from services.appearance_service import age_compatibility, clothing_compatibility
    declared = ' '.join(p for p in (profile.clothing_description, profile.physical_description,
                                    profile.distinctive_marks) if p).strip()
    color = getattr(capture, 'clothing_color', None)
    age = getattr(capture, 'estimated_age', None)
    if color or age is not None:
        reference, _ = parse_datetime(profile.disappearance_datetime)
        years = max(0.0, (moment - reference).days / 365.25) if reference and moment else 0.0
        parts = [clothing_compatibility(profile.clothing_description, color),
                 age_compatibility(profile.declared_age, age, years)]
        evaluable = [(level, text) for level, text in parts if level != 'NO_EVALUABLE']
        if evaluable:
            compatible = sum(level == 'MEDIA' for level, _ in evaluable)
            level = 'MEDIA' if compatible else 'BAJA'
            score = .7 if compatible == len(evaluable) and compatible > 1 else .55 if compatible else .2
            return MatchSignal(level, ' '.join(text for _, text in evaluable), score)
    if not declared:
        return MatchSignal('NO_EVALUABLE', 'La ficha no aporta descriptores para comparar.')
    if not person_reid_service.available():
        return MatchSignal('NO_EVALUABLE', 'Descriptores de la ficha disponibles; comparación visual de '
                                           'apariencia pendiente de integración.')
    return MatchSignal(**person_reid_service.compare(declared, capture))


def _route_signal(case_id, camera, moment, detections):
    """Dos apariciones compatibles en cámaras contiguas refuerzan la prioridad."""
    from services.cameras_service import get_camera
    if not camera or not moment:
        return MatchSignal('NO_EVALUABLE', 'Sin datos suficientes para evaluar continuidad.')
    window = timedelta(minutes=config.SEARCH_ROUTE_WINDOW_MINUTES)
    for other in detections:
        if other.camera_id == camera.id:
            continue
        when, _ = parse_datetime(other.timestamp)
        neighbour = get_camera(other.camera_id)
        if not when or not neighbour or abs(when - moment) > window:
            continue
        if other.camera_id in (camera.nearby_camera_ids or []) or camera.id in (neighbour.nearby_camera_ids or []):
            return MatchSignal('ALTA', f'Aparición compatible en {other.camera_id}, cámara contigua, '
                                       f'a {_human(abs(when - moment))}.', .85)
    return MatchSignal('NO_EVALUABLE', 'No hay otra aparición compatible en cámaras contiguas.')


WEIGHTS = {'face': .45, 'temporal': .2, 'geographic': .2, 'route': .1, 'appearance': .05}
LEVEL_SCORES = {'ALTA': 1.0, 'MEDIA': .6, 'BAJA': .2}


def relevance(signals, linked_event=False):
    """Prioridad de revisión. No es la probabilidad de que la identidad sea correcta.

    Las señales no evaluables se excluyen del promedio en lugar de contar como cero: no
    haber podido comparar algo no es evidencia en contra del candidato.
    """
    total = weight = 0.0
    for name, signal in signals.items():
        if signal.level == 'NO_EVALUABLE':
            continue
        score = signal.score if signal.score is not None else LEVEL_SCORES.get(signal.level, 0)
        total += score * WEIGHTS.get(name, 0)
        weight += WEIGHTS.get(name, 0)
    base = total / weight if weight else 0.0
    # Un evento de auxilio es contexto adicional, no una afirmación sobre la persona.
    return round(min(base + (.05 if linked_event else 0), 1.0), 3)


def priority_level(score):
    """Nivel de la prioridad de revisión, para mostrar en lugar de la cifra interna."""
    return 'ALTA' if score >= .7 else 'MEDIA' if score >= config.CANDIDATE_PRIORITY_THRESHOLD else 'BAJA'


def score_capture(profile, capture, detections=()):
    """Señales de una captura frente a un perfil: (señales, ventana temporal, cámara)."""
    from services.cameras_service import get_camera
    camera = get_camera(capture.camera_id)
    moment, _ = parse_datetime(capture.timestamp)
    signals = {'face': _face_signal(profile, capture.embedding)}
    temporal, window = _temporal_signal(profile, moment)
    signals['temporal'] = temporal
    signals['geographic'] = _geographic_signal(profile, camera, moment)
    signals['appearance'] = _appearance_signal(profile, capture, moment)
    signals['route'] = _route_signal(profile.case_id, camera, moment, detections)
    return signals, window, camera


def detection_signals(detection):
    """(perfil, señales) de una detección frente a la ficha de su propio caso.

    Sin huella guardada (detecciones de demostración) el rostro se evalúa con el nivel que
    registró el módulo facial al detectarla.
    """
    case = next((c for c in store.cases if c.id == detection.case_id), None)
    if case is None:
        return None, {}
    profile = ensure_profile(case)
    detections = [d for d in store.detections if d.case_id == case.id and d.id != detection.id]
    signals, _, _ = score_capture(profile, detection_capture(detection), detections)
    if not detection.embedding or not profile.face_embedding:
        signals['face'] = _face_signal_from_similarity(detection.similarity)
    return profile, signals


def _capture_attributes(capture):
    return {key: value for key, value in (('estimated_age', capture.estimated_age),
                                          ('clothing_color', capture.clothing_color),
                                          ('label', capture.label)) if value not in (None, '')}


# ------------------------------------------------------------------------- la búsqueda
def run_search(case_id, actor=None):
    """Compara el perfil con las capturas almacenadas, incluidas las anteriores a la ficha.

    Recorre las personas vistas en eventos de auxilio, las detecciones del propio caso, las
    detecciones de otros casos que guardaron la huella del rostro (la misma persona pudo
    quedar asociada a otra ficha) y, si está conectada, la base compartida. Pedir ayuda no es
    requisito para ser localizada.
    """
    actor = actor or require('cases.manage')
    profile = get_profile(case_id)
    if not profile:
        raise ValueError('El caso no tiene un perfil de búsqueda confirmado todavía.')
    case = next((c for c in store.cases if c.id == case_id), None)
    if case is not None and not profile.face_embedding:
        profile = ensure_profile(case, actor)
    profile.search_status = 'BUSCANDO'
    profile.search_start_datetime = store.now()
    previous = {c.candidate_match_id for c in store.candidate_matches if c.case_id == case_id}
    detections = [d for d in store.detections if d.case_id == case_id]
    found = []

    # a) personas de eventos, detecciones de otros casos y base compartida: exigen parecido facial.
    for capture in camera_captures():
        if capture.kind == 'DETECCION' and capture.case_id == case_id:
            continue  # las del propio caso van abajo, con o sin huella
        signals, window, camera = score_capture(profile, capture, detections)
        if signals['face'].level == 'NO_EVALUABLE' or (signals['face'].score or 0) < config.FACE_MATCH_THRESHOLD:
            continue  # sin rostro comparable, una captura ajena por sí sola no genera candidato
        found.append(_build(profile, capture, signals, window, camera))

    # b) detecciones del propio caso ya almacenadas por el módulo facial
    for detection in detections:
        capture = detection_capture(detection)
        signals, window, camera = score_capture(profile, capture, detections)
        if not detection.embedding or not profile.face_embedding:
            signals['face'] = _face_signal_from_similarity(detection.similarity)
        found.append(_build(profile, capture, signals, window, camera))

    found.sort(key=lambda c: c.relevance_score, reverse=True)
    found = found[:config.CANDIDATE_MAX_RESULTS]
    store.candidate_matches[:] = [c for c in store.candidate_matches if c.case_id != case_id
                                  or c.status not in ('AI_CANDIDATE', 'PENDING_HUMAN_REVIEW')]
    store.candidate_matches.extend(c for c in found if c.candidate_match_id not in previous)
    profile.search_status = 'CON_CANDIDATOS' if found else 'SIN_CANDIDATOS'
    store.audit(actor, 'Búsqueda',
                f'Búsqueda ejecutada para {case_id}: {len(found)} candidato(s) para revisión humana. '
                'Prioridad de revisión, no identificación.',
                case_id=case_id, result=profile.search_status)
    return found


def _build(profile, capture, signals, window, camera):
    linked = capture.kind == 'EVENTO'
    score = relevance(signals, linked)
    return CandidateMatch(
        candidate_match_id='CM-' + uuid4().hex[:8].upper(), case_id=profile.case_id,
        profile_id=profile.profile_id, camera_id=capture.camera_id, timestamp=capture.timestamp,
        location=camera.location if camera else '', detection_id=capture.detection_id,
        person_candidate_id=capture.person_candidate_id, event_id=capture.event_id,
        face_image_path=capture.image, signals=signals, relevance_score=score,
        capture_kind=capture.kind, capture_attributes=_capture_attributes(capture),
        outcome='CANDIDATO PRIORITARIO' if score >= config.CANDIDATE_PRIORITY_THRESHOLD else 'CANDIDATO',
        temporal_window=window, linked_to_distress_event=linked,
        status='PENDING_HUMAN_REVIEW', created_at=store.now())


def _already_proposed(case_id, capture):
    return any(c.case_id == case_id and (
        (capture.person_candidate_id and c.person_candidate_id == capture.person_candidate_id)
        or (capture.detection_id and c.detection_id == capture.detection_id)
        or (capture.kind == 'CAPTURA_BD' and c.face_image_path == capture.image and c.timestamp == capture.timestamp))
        for c in store.candidate_matches)


def compare_with_active_cases(capture, actor='Sistema'):
    """Una captura nueva contra todas las fichas activas; crea candidatos donde el rostro se parece.

    Es lo que corre solo cuando una cámara ve a alguien en un evento de auxilio: si esa persona
    se parece a alguien que se busca, la comparación queda lista para revisión humana sin que
    nadie tenga que pedirla. Devuelve los candidatos nuevos.
    """
    from services import face_engine
    if not capture.embedding or not face_engine.ready():
        return []
    created = []
    for case in [c for c in store.cases if c.status == 'En búsqueda']:
        profile = ensure_profile(case, actor)
        if not profile.face_embedding or _already_proposed(case.id, capture):
            continue
        detections = [d for d in store.detections if d.case_id == case.id]
        signals, window, camera = score_capture(profile, capture, detections)
        if (signals['face'].score or 0) < config.FACE_MATCH_THRESHOLD:
            continue
        candidate = _build(profile, capture, signals, window, camera)
        store.candidate_matches.insert(0, candidate)
        created.append(candidate)
        store.audit(actor, 'Coincidencia',
                    f'{capture.label or capture.capture_id} se parece a la ficha {case.id} '
                    f'(nivel {signals["face"].level}). Candidato {candidate.candidate_match_id} para revisión humana.',
                    case_id=case.id, camera_id=capture.camera_id, result='PENDING_HUMAN_REVIEW')
    return created


def match_event_candidates(event_id, actor='Sistema'):
    """Las personas vistas en un evento, contra todas las fichas activas."""
    created = []
    for candidate in [c for c in store.person_candidates if c.event_id == event_id and c.face_embedding]:
        created += compare_with_active_cases(event_capture(candidate), actor)
    return created


def retro_search_new_case(case_id, actor='Sistema'):
    """Ficha recién registrada contra lo que las cámaras ya guardaron. Sólo si el modelo está listo.

    No crea candidatos por detecciones propias (todavía no las hay): busca en eventos,
    detecciones de otros casos y la base compartida. Devuelve los candidatos nuevos.
    """
    from services import face_engine
    case = next((c for c in store.cases if c.id == case_id), None)
    if case is None or not face_engine.ready():
        return []
    profile = ensure_profile(case, actor)
    if not profile.face_embedding:
        return []
    created = []
    for capture in camera_captures():
        if (capture.kind == 'DETECCION' and capture.case_id == case_id) or _already_proposed(case_id, capture):
            continue
        signals, window, camera = score_capture(profile, capture)
        if (signals['face'].score or 0) < config.FACE_MATCH_THRESHOLD:
            continue
        candidate = _build(profile, capture, signals, window, camera)
        store.candidate_matches.insert(0, candidate)
        created.append(candidate)
    if created:
        store.audit(actor, 'Búsqueda', f'La ficha {case_id} se parece a {len(created)} captura(s) ya '
                                       'registradas por las cámaras. Pendiente de revisión humana.',
                    case_id=case_id, result='CON_CANDIDATOS')
    return created


def search_by_profile(profile, include_database=True, limit=None):
    """Búsqueda de consulta: el perfil contra todas las capturas, sin crear candidatos.

    Devuelve dicts ordenados por prioridad de revisión, con las señales y los rasgos listos
    para la comparación lado a lado. Es la base de la página «Búsqueda por ficha».
    """
    results = []
    own = [d for d in store.detections if profile.case_id and d.case_id == profile.case_id]
    for capture in camera_captures(include_database):
        signals, window, camera = score_capture(profile, capture, own)
        if (signals['face'].score or 0) < config.FACE_MATCH_THRESHOLD:
            continue
        score = relevance(signals, capture.kind == 'EVENTO')
        results.append({'capture': capture, 'signals': signals, 'window': window, 'camera': camera,
                        'relevance': score, 'priority': priority_level(score),
                        'similarity': signals['face'].score, 'level': signals['face'].level})
    results.sort(key=lambda r: (r['relevance'], r['similarity'] or 0), reverse=True)
    return results[:limit or config.CANDIDATE_MAX_RESULTS]


def similar_cases(embedding, exclude_case_id=None):
    """Fichas registradas cuyo rostro se parece a una referencia: posibles duplicados."""
    from services import face_engine
    if not embedding or not face_engine.ready():
        return []
    matches = []
    for case in store.cases:
        if case.id == exclude_case_id:
            continue
        profile = ensure_profile(case)
        if not profile.face_embedding:
            continue
        value = face_engine.similarity(embedding, profile.face_embedding)
        level = face_engine.level_of(value)
        if level:
            matches.append({'case': case, 'profile': profile, 'similarity': round(float(value), 3), 'level': level})
    return sorted(matches, key=lambda m: -m['similarity'])[:6]


def promote_result(profile, capture, actor=None):
    """Envía un resultado de la búsqueda por ficha a la cola de revisión del caso."""
    actor = actor or require('cases.manage')
    if not profile.case_id:
        raise ValueError('Crea o vincula primero el caso de la ficha para enviarlo a revisión.')
    existing = next((c for c in store.candidate_matches if c.case_id == profile.case_id and (
        (capture.person_candidate_id and c.person_candidate_id == capture.person_candidate_id) or
        (capture.detection_id and c.detection_id == capture.detection_id) or
        (capture.kind == 'CAPTURA_BD' and c.face_image_path == capture.image and c.timestamp == capture.timestamp))),
        None)
    if existing:
        return existing
    detections = [d for d in store.detections if d.case_id == profile.case_id]
    signals, window, camera = score_capture(profile, capture, detections)
    candidate = _build(profile, capture, signals, window, camera)
    store.candidate_matches.insert(0, candidate)
    store.audit(actor, 'Búsqueda', f'{actor} envió a revisión la captura {capture.label or capture.capture_id} '
                                   f'para la ficha {profile.case_id} ({candidate.candidate_match_id}).',
                case_id=profile.case_id, camera_id=capture.camera_id, result='PENDING_HUMAN_REVIEW')
    return candidate


# ------------------------------------------------------------------------ revisión humana
def get_candidates(case_id=None, status=None, event_id=None):
    return [c for c in store.candidate_matches
            if (case_id is None or c.case_id == case_id) and (status is None or c.status == status)
            and (event_id is None or c.event_id == event_id)]


def get_candidate(candidate_match_id):
    return next((c for c in store.candidate_matches if c.candidate_match_id == candidate_match_id), None)


def _require_candidate(candidate_match_id):
    candidate = get_candidate(candidate_match_id)
    if not candidate:
        raise ValueError('No se encontró el candidato indicado.')
    return candidate


def operator_review(candidate_match_id, accept, notes=''):
    """El operador descarta o envía a supervisión. No puede confirmar una identidad."""
    actor = require('matches.review')
    candidate = _require_candidate(candidate_match_id)
    if candidate.status not in ('AI_CANDIDATE', 'PENDING_HUMAN_REVIEW'):
        raise ValueError('Este candidato ya fue revisado.')
    candidate.status = 'OPERATOR_ACCEPTED_FOR_REVIEW' if accept else 'OPERATOR_REJECTED'
    candidate.reviewed_by, candidate.reviewed_at = actor, store.now()
    candidate.review_notes = (notes or '')[:500]
    store.audit(actor, 'Revisión',
                f'{actor} {"envió a supervisión" if accept else "descartó"} el candidato '
                f'{candidate.candidate_match_id} ({candidate.camera_id}).',
                case_id=candidate.case_id, camera_id=candidate.camera_id, result=candidate.status)
    return candidate


def supervisor_review(candidate_match_id, validate, notes=''):
    """Validar significa relevante para la investigación, no identidad confirmada."""
    actor = require('matches.supervise')
    candidate = _require_candidate(candidate_match_id)
    if candidate.status != 'OPERATOR_ACCEPTED_FOR_REVIEW':
        raise ValueError('Sólo pueden resolverse candidatos enviados por un operador.')
    candidate.status = 'SUPERVISOR_VALIDATED' if validate else 'SUPERVISOR_REJECTED'
    candidate.supervised_by, candidate.supervised_at = actor, store.now()
    candidate.review_notes = (notes or candidate.review_notes)[:500]
    if validate:
        # Sigue siendo información interna: comunicarla fuera exigiría otra autorización.
        candidate.disclosure_status = 'VALIDATED_FOR_INVESTIGATION'
    store.audit(actor, 'Revisión',
                f'{actor} {"validó para investigación" if validate else "rechazó"} el candidato '
                f'{candidate.candidate_match_id}. Identidad no confirmada legalmente.',
                case_id=candidate.case_id, camera_id=candidate.camera_id, result=candidate.status)
    return candidate


# ------------------------------------------------------------- trayectoria y ubicación
def tracking_timeline(case_id):
    """Puntos observados en orden. No se inventa el camino entre ellos."""
    points = [c for c in get_candidates(case_id)
              if c.status in ('SUPERVISOR_VALIDATED', 'OPERATOR_ACCEPTED_FOR_REVIEW', 'PENDING_HUMAN_REVIEW')]
    return sorted(points, key=lambda c: c.timestamp)


def last_locations(case_id):
    """Última detección validada y última posible, separadas y nunca mezcladas."""
    candidates = sorted(get_candidates(case_id), key=lambda c: c.timestamp)
    validated = [c for c in candidates if c.status == 'SUPERVISOR_VALIDATED']
    possible = [c for c in candidates if c.status in ('PENDING_HUMAN_REVIEW', 'OPERATOR_ACCEPTED_FOR_REVIEW')]
    return {'validated': validated[-1] if validated else None,
            'possible': possible[-1] if possible else None}


def nearby_cameras_to_search(candidate):
    """Cámaras contiguas donde tendría sentido seguir buscando tras una detección prioritaria."""
    from services.cameras_service import get_camera
    camera = get_camera(candidate.camera_id)
    if not camera:
        return []
    return [get_camera(cid) for cid in (camera.nearby_camera_ids or []) if get_camera(cid)]
