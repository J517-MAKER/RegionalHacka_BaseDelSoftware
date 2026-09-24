from models.alert import EmergencyAlert
from services import store
from services.users_service import require
from uuid import uuid4


def get_alerts():
    return store.alerts


def get_alert(alert_id):
    return next((a for a in store.alerts if a.id==alert_id),None)


def get_alert_event(alert):
    return next(v for v in store.voice_events if v.id==alert.voice_event_id)


def create_voice_alert(event):
    existing = next((a for a in store.alerts if a.voice_event_id==event.id),None)
    if existing:
        return existing
    if event.intent != 'SOLICITUD_AUXILIO':
        raise ValueError('Sólo las posibles solicitudes de auxilio generan alertas.')
    alert = EmergencyAlert('ALERT-' + uuid4().hex[:12].upper(),event.id, priority=event.priority)
    store.alerts.insert(0,alert)
    store.audit('Sistema','Voz',f'Sistema detectó posible solicitud de auxilio en {event.camera_id}. {alert.id}; {event.classification}; prioridad {event.priority}',camera_id=event.camera_id,result='PENDIENTE_REVISION')
    return alert


def start_alert_tracking(alert_id):
    """Confirma el seguimiento de las personas del evento en las cámaras del equipo."""
    actor = require('tracking.control')
    alert = get_alert(alert_id)
    if not alert:
        raise ValueError('No se encontró la alerta.')
    from services.voice_integrations import start_tracking_from_alert
    voice_event = get_alert_event(alert)
    camera_id = voice_event.camera_id
    result = start_tracking_from_alert(alert.id, camera_id)
    alert.tracking_requested = True
    if voice_event.evidence_id:
        # Con evidencia hay rostros del evento que buscar: el seguimiento es real.
        from services.tracking_service import confirm_event_tracking
        confirm_event_tracking(voice_event.evidence_id, actor)
        result = dict(result, status='TRACKING_ACTIVE', mock=False, event_id=voice_event.evidence_id)
        alert.tracking_started = True
    store.audit(actor,'Seguimiento',f'Operador solicitó seguimiento desde {camera_id}. {alert.id}',camera_id=camera_id,result=result['status'])
    return result
