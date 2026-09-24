from models.detection import TrackingEvent
from services import store
from services.users_service import require


def get_tracking_history(case_id):
    detections = sorted((d for d in store.detections if d.case_id==case_id), key=lambda d:d.timestamp)
    return [TrackingEvent(d,i+1) for i,d in enumerate(detections)]


def start_tracking(case_id):
    actor = require('track')
    case = next((c for c in store.cases if c.id==case_id),None)
    if not case:
        raise ValueError('No se encontró el caso.')
    case.status = 'En búsqueda'
    store.audit(actor,'Seguimiento','Seguimiento iniciado',case_id)


def stop_tracking(case_id):
    actor = require('track')
    case = next((c for c in store.cases if c.id==case_id),None)
    if not case:
        raise ValueError('No se encontró el caso.')
    case.status = 'Pausada'
    store.audit(actor,'Seguimiento','Búsqueda pausada',case_id)
