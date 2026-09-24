"""Fotogramas conservados alrededor de un evento y personas candidatas halladas en ellos.

Un evento no se resuelve con una sola imagen: el rostro puede estar girado, borroso u
ocluido, así que se conservan varios fotogramas y de ellos se derivan candidatos.
Ninguna persona candidata se etiqueta como víctima: sólo queda asociada al evento.
"""
from dataclasses import dataclass, field

FRAME_STATES = ('CAPTURADO', 'PROCESADO', 'SIN_ROSTRO', 'PENDIENTE_INTEGRACION')
CANDIDATE_SOURCES = ('EVENTO_AUXILIO', 'DETECCION_CONTINUA')


@dataclass
class EventFrame:
    frame_id: str
    event_id: str
    camera_id: str
    timestamp: str
    image_path: str = ''
    face_detected: bool = False
    quality_score: float | None = None
    processing_status: str = 'CAPTURADO'
    offset_seconds: float = 0.0
    # Motivo cuando no pudo capturarse: el fotograma se declara pendiente, nunca se inventa.
    note: str = ''


@dataclass
class DetectedPersonCandidate:
    """Una persona vista en el evento. Es una pista, no una identidad."""
    candidate_id: str
    event_id: str
    camera_id: str
    timestamp: str
    person_track_id: str = ''
    face_image_path: str = ''
    face_embedding: list = field(default_factory=list)
    face_quality: float = 0.0
    source_frame_id: str = ''
    source_type: str = 'EVENTO_AUXILIO'
    # Rasgos estimados de la imagen, sólo orientativos al compararla con una ficha.
    estimated_age: int | None = None
    clothing_color: str | None = None
    # Apariencia para Re-ID futura; vacía mientras el módulo no exista.
    appearance_embedding: list = field(default_factory=list)
    appearance_status: str = 'PENDIENTE_INTEGRACION'
    note: str = ''
