from dataclasses import dataclass


@dataclass
class Match:
    id: str
    detection_id: str
    status: str = 'Pendiente de validación'
    reviewed_by: str = ''
    reviewed_at: str = ''
