"""Evidence of a possible request for help. The stored audio is immutable."""
from dataclasses import dataclass, field
from models.risk_assessment import RiskAssessment

REVIEW_STATES = ('PENDIENTE_REVISION', 'EN_REVISION', 'CONFIRMADO_PARA_ATENCION', 'FALSO_POSITIVO',
                 'DELETION_REQUESTED', 'DELETION_APPROVED', 'DELETION_REJECTED')


@dataclass
class EvidenceEvent:
    event_id: str
    camera_id: str
    location: str
    created_at: str

    classification: str
    priority: str

    audio_file: str = ''
    audio_start_timestamp: str = ''
    audio_end_timestamp: str = ''
    audio_duration: float = 0.0

    transcript_original: str = ''
    transcript_normalized: str = ''
    transcript_segments: list = field(default_factory=list)

    semantic_analysis: dict = field(default_factory=dict)
    acoustic_analysis: dict = field(default_factory=dict)
    assessment: RiskAssessment | None = None

    review_status: str = 'PENDIENTE_REVISION'
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_notes: str = ''

    # Instante en que se escuchó la frase: el clip abarca unos segundos antes y después.
    trigger_timestamp: str = ''

    # Camera module; audio and video share the same event_id.
    video_file: str | None = None
    video_start_timestamp: str | None = None
    video_end_timestamp: str | None = None
    video_status: str = 'PENDING_INTEGRATION'
    # SHA-256 del clip al escribirlo: el video también debe poder verificarse.
    video_integrity_hash: str = ''
    # El clip lleva el mismo audio del evento, sincronizado con la imagen.
    video_has_audio: bool = False
    # Cámara de la que salió el clip (puede ser otra si la del micrófono no transmitía).
    video_camera_id: str = ''
    # Otros ángulos del mismo instante: [{'camera_id', 'file', 'integrity_hash'}].
    extra_videos: list = field(default_factory=list)
    # Faces in view of the same camera when the event was created (live recognition).
    face_captures: list = field(default_factory=list)

    # Seguimiento de las personas del evento en las demás cámaras del equipo. Arranca solo y
    # por poco tiempo (PROVISIONAL); una persona lo confirma o lo detiene.
    # SIN_SEGUIMIENTO · PROVISIONAL · CONFIRMADO · DETENIDO
    tracking_status: str = 'SIN_SEGUIMIENTO'
    tracking_until: str = ''

    integrity_hash: str = ''
    voice_event_id: str = ''
