from dataclasses import dataclass
from models.semantic_analysis import SemanticAnalysis
from models.acoustic_features import AcousticFeatures


@dataclass
class RiskAssessment:
    classification: str
    priority: str
    should_create_alert: bool
    semantic_analysis: SemanticAnalysis
    acoustic_summary: AcousticFeatures
    semantic_signal: str
    acoustic_signal: str
    context_break: bool
