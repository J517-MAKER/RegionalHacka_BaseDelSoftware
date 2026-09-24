from dataclasses import dataclass


@dataclass
class Detection:
    id: str
    case_id: str
    camera_id: str
    timestamp: str
    similarity: int
    status: str = 'Pendiente de validación'
    quality: str = 'Adecuada'
    capture: str = '/assets/demo/capture.svg'


@dataclass
class TrackingEvent:
    detection: Detection
    order: int
