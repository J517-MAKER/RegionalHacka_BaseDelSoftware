"""Motor de búsqueda multimodal: de una ficha a candidatos priorizados.

Lo que este módulo NO hace: decir que una detección es una persona. Combina señales
independientes —rostro, tiempo, lugar, apariencia y continuidad de ruta— y las conserva por
separado, porque una sola cifra escondería de dónde viene la sospecha. La puntuación
combinada ordena la cola de revisión; no es la probabilidad de que la identidad sea correcta.

Importar una ficha y buscar son pasos distintos: el perfil se crea cuando un operador ya
confirmó la fotografía y corrigió el OCR. La búsqueda mira también hacia atrás, porque una
ficha registrada hoy puede corresponder a una detección de la semana pasada.
"""
import re
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


def create_search_profile(case_id, reference_photo='', face_embedding=None, actor=None,
                          face_status='PENDIENTE', face_message=''):
    """Crea el perfil a partir del caso ya revisado. Un caso tiene un único perfil vigente."""
    actor = actor or require('cases.manage')
    case = next((c for c in store.cases if c.id == case_id), None)
    if not case:
        raise ValueError('No se encontró el caso para crear el perfil de búsqueda.')
    moment, time_known = parse_datetime(case.missing_date)
    if moment and not time_known and case.missing_time and case.missing_time != 'Desconocida':
        hour, _ = parse_datetime(f'{moment:%Y-%m-%d} {case.missing_time}')
        if hour:
            moment, time_known = hour, True
    existing = get_profile(case_id)
    profile = existing or SearchProfile('SP-' + uuid4().hex[:8].upper(), case_id, store.now(), actor)
    profile.official_folio = case.id
    profile.reference_photo = reference_photo or (case.person.photos[0] if case.person.photos else '')
    profile.face_embedding = list(face_embedding or profile.face_embedding)
    profile.face_status = face_status if face_embedding or face_status != 'PENDIENTE' else profile.face_status
    profile.face_message = face_message or profile.face_message
    profile.disappearance_datetime = moment.strftime('%Y-%m-%d %H:%M:%S') if moment else ''
    profile.disappearance_time_known = time_known
    profile.report_datetime = case.reported_at or ''
    profile.last_known_location = case.location or ''
    profile.last_known_camera_id = _camera_for_location(case.location)
    profile.physical_description = ' · '.join(p for p in (case.person.build, case.person.height,
                                                          case.person.hair) if p and 'Desconocid' not in p)
    profile.distinctive_marks = case.person.marks or ''
    profile.clothing_description = case.person.clothing or ''
    if not existing:
        store.search_profiles.insert(0, profile)
    store.audit(actor, 'Búsqueda',
                f'Perfil de búsqueda {profile.profile_id} creado para {case_id}. '
                f'Referencia facial: {profile.face_status}.', case_id=case_id, result='PERFIL_CREADO')
    return profile


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


# ----------------------------------------------------------------------------- señales
def _face_signal(profile, embedding):
    from services import face_engine
    if not profile.face_embedding or not embedding:
        return MatchSignal('NO_EVALUABLE', 'Sin huella facial comparable en la ficha o en la detección.')
    value = face_engine.similarity(profile.face_embedding, embedding)
    level = face_engine.level_of(value) or 'BAJA'
    return MatchSignal(level, f'Similitud facial orientativa de {value:.2f} sobre el modelo de referencia.',
                       round(float(value), 3))


def _face_signal_from_similarity(percent):
    """Detecciones ya almacenadas guardan un porcentaje, no la huella completa."""
    if percent is None:
        return MatchSignal('NO_EVALUABLE', 'La detección almacenada no conserva una medida de similitud.')
    value = percent / 100
    level = 'ALTA' if value >= config.FACE_LEVEL_HIGH else 'MEDIA' if value >= config.FACE_LEVEL_MEDIUM \
        else 'BAJA' if value >= config.FACE_MATCH_THRESHOLD else 'BAJA'
    return MatchSignal(level, f'Similitud registrada por el módulo facial: {percent} %.', round(value, 3))


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


def _geographic_signal(profile, camera):
    """La cercanía prioriza; la lejanía nunca excluye."""
    from services.cameras_service import get_camera
    origin = get_camera(profile.last_known_camera_id) if profile.last_known_camera_id else None
    if not camera:
        return MatchSignal('NO_EVALUABLE', 'La detección no indica cámara.')
    if not origin:
        if profile.last_known_location and profile.last_known_location.lower() in camera.name.lower():
            return MatchSignal('ALTA', f'La cámara corresponde al último lugar conocido: {camera.name}.', .9)
        return MatchSignal('NO_EVALUABLE', 'El último lugar conocido no se pudo situar en la red de cámaras.')
    distance = ((camera.x - origin.x) ** 2 + (camera.y - origin.y) ** 2) ** .5
    if distance <= config.SEARCH_NEAR_DISTANCE:
        return MatchSignal('ALTA', f'A corta distancia del último punto conocido ({origin.id}).',
                           round(1 - distance / config.SEARCH_FAR_DISTANCE, 3))
    if distance <= config.SEARCH_FAR_DISTANCE:
        return MatchSignal('MEDIA', f'En el área ampliada alrededor de {origin.id}.',
                           round(1 - distance / config.SEARCH_FAR_DISTANCE, 3))
    return MatchSignal('BAJA', f'Lejos del último punto conocido ({origin.id}). No se descarta: '
                               'la ubicación prioriza, no excluye.', .1)


def _appearance_signal(profile, candidate):
    """Sólo compara lo que la ficha declara. Nada se infiere de la imagen."""
    from services import person_reid_service
    declared = ' '.join(p for p in (profile.clothing_description, profile.physical_description,
                                    profile.distinctive_marks) if p).strip()
    if not declared:
        return MatchSignal('NO_EVALUABLE', 'La ficha no aporta descriptores para comparar.')
    if not person_reid_service.available():
        return MatchSignal('NO_EVALUABLE', 'Descriptores de la ficha disponibles; comparación visual de '
                                           'apariencia pendiente de integración.')
    return MatchSignal(**person_reid_service.compare(declared, candidate))


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


# ------------------------------------------------------------------------- la búsqueda
def run_search(case_id, actor=None):
    """Compara el perfil con las detecciones almacenadas, incluidas las anteriores a la ficha.

    Recorre dos fuentes: las personas candidatas de eventos de auxilio y las detecciones
    normales del módulo facial. Pedir ayuda no es requisito para ser localizada.
    """
    actor = actor or require('cases.manage')
    profile = get_profile(case_id)
    if not profile:
        raise ValueError('El caso no tiene un perfil de búsqueda confirmado todavía.')
    from services.cameras_service import get_camera
    profile.search_status = 'BUSCANDO'
    profile.search_start_datetime = store.now()
    previous = {c.candidate_match_id for c in store.candidate_matches if c.case_id == case_id}
    detections = [d for d in store.detections if d.case_id == case_id]
    found = []

    # a) personas candidatas asociadas a eventos de auxilio
    for candidate in store.person_candidates:
        camera = get_camera(candidate.camera_id)
        moment, _ = parse_datetime(candidate.timestamp)
        signals = {'face': _face_signal(profile, candidate.face_embedding)}
        temporal, window = _temporal_signal(profile, moment)
        signals['temporal'] = temporal
        signals['geographic'] = _geographic_signal(profile, camera)
        signals['appearance'] = _appearance_signal(profile, candidate)
        signals['route'] = _route_signal(case_id, camera, moment, detections)
        if signals['face'].level in ('NO_EVALUABLE', 'BAJA') and not profile.face_embedding:
            continue  # sin rostro comparable, un evento por sí solo no genera candidato
        found.append(_build(profile, candidate.camera_id, candidate.timestamp, signals, window,
                            camera, person_candidate_id=candidate.candidate_id,
                            event_id=candidate.event_id, face_image_path=candidate.face_image_path,
                            linked_event=True))

    # b) detecciones normales ya almacenadas por el módulo facial
    for detection in detections:
        camera = get_camera(detection.camera_id)
        moment, _ = parse_datetime(detection.timestamp)
        signals = {'face': _face_signal_from_similarity(detection.similarity)}
        temporal, window = _temporal_signal(profile, moment)
        signals['temporal'] = temporal
        signals['geographic'] = _geographic_signal(profile, camera)
        signals['appearance'] = _appearance_signal(profile, detection)
        signals['route'] = _route_signal(case_id, camera, moment, detections)
        found.append(_build(profile, detection.camera_id, detection.timestamp, signals, window,
                            camera, detection_id=detection.id, face_image_path=detection.capture))

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


def _build(profile, camera_id, timestamp, signals, window, camera, detection_id='',
           person_candidate_id='', event_id='', face_image_path='', linked_event=False):
    score = relevance(signals, linked_event)
    return CandidateMatch(
        candidate_match_id='CM-' + uuid4().hex[:8].upper(), case_id=profile.case_id,
        profile_id=profile.profile_id, camera_id=camera_id, timestamp=timestamp,
        location=camera.location if camera else '', detection_id=detection_id,
        person_candidate_id=person_candidate_id, event_id=event_id,
        face_image_path=face_image_path, signals=signals, relevance_score=score,
        outcome='CANDIDATO PRIORITARIO' if score >= config.CANDIDATE_PRIORITY_THRESHOLD else 'CANDIDATO',
        temporal_window=window, linked_to_distress_event=linked_event,
        status='PENDING_HUMAN_REVIEW', created_at=store.now())


# ------------------------------------------------------------------------ revisión humana
def get_candidates(case_id=None, status=None):
    return [c for c in store.candidate_matches
            if (case_id is None or c.case_id == case_id) and (status is None or c.status == status)]


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
