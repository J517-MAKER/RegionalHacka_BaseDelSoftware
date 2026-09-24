from dataclasses import dataclass


@dataclass
class EmergencyAlert:
    id: str
    voice_event_id: str
    status: str = 'PENDIENTE_REVISION'
    reviewed_by: str = ''
    reviewed_at: str = ''
    tracking_started: bool = False
    tracking_requested: bool = False
    priority: str = 'MEDIA'
