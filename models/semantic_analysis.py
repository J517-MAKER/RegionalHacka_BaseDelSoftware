from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Classification = Literal['NORMAL', 'AMBIGUO', 'POSIBLE_AUXILIO', 'ALTA_PRIORIDAD']


class SemanticAnalysis(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    classification: Classification
    semantic_risk: Literal['LOW', 'MODERATE', 'HIGH']
    context_change: bool
    request_is_current: bool | None
    temporal_context: Literal['CURRENT', 'PAST', 'HYPOTHETICAL', 'QUOTED', 'UNKNOWN']
    signals: list[str] = Field(max_length=12)
    reason: str = Field(max_length=600)
    mode: Literal['IA contextual', 'Fallback local'] = 'Fallback local'
    fallback_reason: str | None = None
