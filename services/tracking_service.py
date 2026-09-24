"""Seguimiento: detecciones de un caso y reapariciones de las personas de un evento.

Un caso se sigue por sus detecciones (la ficha contra las cámaras). Un evento de auxilio se
sigue por sus personas: el rostro de cada una se busca en las demás cámaras del equipo durante
un tiempo acotado, y cada reaparición queda como un punto del trayecto, pendiente de revisión.
"""
import time
from datetime import datetime, timedelta
from uuid import uuid4
import config
from models.detection import TrackingEvent
from models.track_sighting import TrackSighting
from services import store
from services.users_service import require

# Una evidencia en estos estados no justifica seguir buscando a nadie.
STOPPED_REVIEW_STATES = ('FALSO_POSITIVO', 'DELETION_REQUESTED', 'DELETION_APPROVED')
_last_sighting = {}  # (candidate_id, camera_id) -> monotonic del último registro


def get_tracking_history(case_id):
    detections = sorted((d for d in store.detections if d.case_id==case_id), key=lambda d:d.timestamp)
    return [TrackingEvent(d,i+1) for i,d in enumerate(detections)]


def start_tracking(case_id):
    actor = require('tracking.control')
    case = next((c for c in store.cases if c.id==case_id),None)
    if not case:
        raise ValueError('No se encontró el caso.')
    case.status = 'En búsqueda'
    store.audit(actor,'Seguimiento','Seguimiento iniciado',case_id)


def stop_tracking(case_id):
    actor = require('tracking.control')
    case = next((c for c in store.cases if c.id==case_id),None)
    if not case:
        raise ValueError('No se encontró el caso.')
    case.status = 'Pausada'
    store.audit(actor,'Seguimiento','Búsqueda pausada',case_id)


# ------------------------------------------------------- personas de un evento de auxilio
def _event(event_id):
    return next((e for e in store.evidence if e.event_id == event_id), None)


def _until(**delta):
    return (datetime.now() + timedelta(**delta)).strftime('%Y-%m-%d %H:%M:%S')


def open_event_tracking(event_id):
    """Seguimiento provisional automático, apenas hay personas del evento con rostro."""
    event = _event(event_id)
    if not event or event.tracking_status != 'SIN_SEGUIMIENTO':
        return event
    event.tracking_status, event.tracking_until = 'PROVISIONAL', _until(minutes=config.EVENT_TRACKING_MINUTES)
    store.audit('Sistema', 'Seguimiento',
                f'Seguimiento provisional de las personas de {event_id} en las cámaras del equipo '
                f'durante {config.EVENT_TRACKING_MINUTES} min. Pendiente de confirmación humana.',
                camera_id=event.camera_id, result='PROVISIONAL')
    return event


def confirm_event_tracking(event_id, actor):
    event = _event(event_id)
    if not event:
        raise ValueError('No se encontró la evidencia del evento.')
    if event.review_status in STOPPED_REVIEW_STATES:
        raise ValueError('La evidencia está marcada como falso positivo o en eliminación: no se sigue a nadie.')
    event.tracking_status = 'CONFIRMADO'
    event.tracking_until = _until(hours=config.EVENT_TRACKING_CONFIRMED_HOURS)
    store.audit(actor, 'Seguimiento', f'{actor} confirmó el seguimiento de las personas de {event_id} '
                                      f'por {config.EVENT_TRACKING_CONFIRMED_HOURS} h.',
                camera_id=event.camera_id, result='CONFIRMADO')
    return event


def stop_event_tracking(event_id, actor):
    event = _event(event_id)
    if not event:
        raise ValueError('No se encontró la evidencia del evento.')
    event.tracking_status = 'DETENIDO'
    store.audit(actor, 'Seguimiento', f'{actor} detuvo el seguimiento de las personas de {event_id}.',
                camera_id=event.camera_id, result='DETENIDO')
    return event


def tracking_active(event):
    if event is None or event.tracking_status not in ('PROVISIONAL', 'CONFIRMADO'):
        return False
    if event.review_status in STOPPED_REVIEW_STATES:
        return False
    return bool(event.tracking_until) and event.tracking_until > datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def watch_targets():
    """(persona del evento, huella) de los eventos con seguimiento vigente."""
    active = {e.event_id for e in store.evidence if tracking_active(e)}
    return [(candidate, candidate.face_embedding) for candidate in store.person_candidates
            if candidate.event_id in active and candidate.face_embedding]


def record_sighting(candidate, camera_id, similarity, level, capture=''):
    """Una reaparición por persona y cámara en cada ventana: el trayecto no se llena de repeticiones."""
    key, now = (candidate.candidate_id, camera_id), time.monotonic()
    if now - _last_sighting.get(key, float('-inf')) < config.TRACK_SIGHTING_COOLDOWN_SECONDS:
        return None
    _last_sighting[key] = now
    sighting = TrackSighting('SGT-' + uuid4().hex[:8].upper(), candidate.event_id, candidate.candidate_id,
                             candidate.person_track_id, camera_id, store.now(), round(float(similarity), 3),
                             level, capture)
    store.track_sightings.insert(0, sighting)
    store.audit('Sistema', 'Seguimiento',
                f'{candidate.person_track_id} de {candidate.event_id} reapareció en {camera_id} '
                f'(parecido {level}). Pendiente de revisión.',
                camera_id=camera_id, result='AVISTAMIENTO')
    return sighting


def get_track_sightings(candidate_id=None, event_id=None):
    """Reapariciones en orden cronológico."""
    return sorted((s for s in store.track_sightings
                   if (candidate_id is None or s.candidate_id == candidate_id)
                   and (event_id is None or s.event_id == event_id)), key=lambda s: s.timestamp)
