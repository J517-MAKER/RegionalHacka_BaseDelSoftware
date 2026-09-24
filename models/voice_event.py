from dataclasses import dataclass, field
from models.risk_assessment import RiskAssessment


@dataclass
class VoiceEvent:
    id: str
    timestamp: str
    camera_id: str
    text_original: str
    intent: str = 'SOLICITUD_AUXILIO'
    confidence: float | None = None
    subtype: str | None = 'POSIBLE_SEGUIMIENTO'
    status: str = 'PENDIENTE_REVISION'
    location: str = ''
    text_normalized: str = ''
    source: str = 'DEMO_TEXT'
    action: str | None = None
    parameters: dict = field(default_factory=dict)
    recognition_metadata: dict = field(default_factory=dict)
    command_result: dict = field(default_factory=dict)
    classification: str = 'POSIBLE_AUXILIO'
    priority: str = 'MEDIA'
    assessment: RiskAssessment | None = None
    evidence_id: str | None = None
    expires_at: float | None = None

    @property
    def transcript(self):
        """Compatibility with the existing monitor and tracking views."""
        return self.text_original
