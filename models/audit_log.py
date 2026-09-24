from dataclasses import dataclass


@dataclass
class AuditLog:
    timestamp: str
    user: str
    kind: str
    description: str
    case_id: str = '—'
    camera_id: str = '—'
    result: str = 'Registrado'
    device: str = '—'
