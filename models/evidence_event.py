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

    # Reserved for the camera module; audio and video share the same event_id.
    video_file: str | None = None
    video_start_timestamp: str | None = None
    video_end_timestamp: str | None = None
    video_status: str = 'PENDING_INTEGRATION'
    # Faces in view of the same camera when the event was created (live recognition).
    face_captures: list = field(default_factory=list)

    integrity_hash: str = ''
    voice_event_id: str = ''
