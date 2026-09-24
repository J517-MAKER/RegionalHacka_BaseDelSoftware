"""Repositorio en memoria. Único punto que conoce los datos de demostración."""
from datetime import datetime
import config
from mocks.alerts import seed_alerts
from mocks.cameras import seed_cameras
from mocks.cases import seed_cases
from mocks.detections import seed_detections, seed_matches
from mocks.users import seed_users
from mocks.voice_events import PHRASES, seed_voice_events
from models.audit_log import AuditLog

cases = seed_cases()
cameras = seed_cameras()
detections = seed_detections()
matches = seed_matches()
voice_events = seed_voice_events()
alerts = seed_alerts()
evidence = []
imports = []
deletion_requests = []
# Flujo de búsqueda: fotogramas del evento, personas candidatas, perfiles y candidatos.
event_frames = []
person_candidates = []
search_profiles = []
candidate_matches = []
users = seed_users()
phrases = list(PHRASES)
settings = {'General': {'Nombre del centro': 'Centro de operaciones · Región Centro'},
            'Cámaras': {'Intervalo de actualización (s)': 15},
            'Voz': {'Revisión humana obligatoria': True},
            'Reconocimiento': {'Umbral orientativo de similitud (%)': 75},
            'Seguridad': {'Tiempo de sesión de demostración (min)': 30},
            'Integraciones': {'Modo de servicio': 'Mock local'}}
logs = [AuditLog('2026-09-23 10:25:41','Sistema','Coincidencia','Posible coincidencia detectada', 'BUS-2026-0184','CAM-012','Pendiente de validación'),
        AuditLog('2026-09-23 10:23:02','Sistema','Coincidencia','Posible coincidencia detectada', 'BUS-2026-0184','CAM-007'),
        AuditLog('2026-09-23 10:21:14','Sistema','Coincidencia','Posible coincidencia detectada', 'BUS-2026-0184','CAM-003'),
        AuditLog('2026-09-23 09:39:03','Sistema','Voz','Posible solicitud de auxilio','—','CAM-008','Pendiente de revisión'),
        AuditLog('2026-09-23 09:34:18','Operador01','Búsqueda','Inició búsqueda','BUS-2026-0184'),
        AuditLog('2026-09-23 09:31:54','Operador02','Revisión','Descartó coincidencia','BUS-2026-0185','CAM-004','Descartada')]


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def audit(user, kind, description, case_id='—', camera_id='—', result='Registrado'):
    logs.insert(0, AuditLog(now(), user, kind, description, case_id, camera_id, result, config.DEVICE_ID))
