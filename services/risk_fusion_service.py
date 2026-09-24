from models.acoustic_features import AcousticFeatures
from models.risk_assessment import RiskAssessment


def fuse_evidence(semantic, acoustic=None):
    acoustic = acoustic or AcousticFeatures()
    classification = semantic.classification
    # Unknown/past requests must never escalate based on audio alone.
    if classification in ('POSIBLE_AUXILIO', 'ALTA_PRIORIDAD') and semantic.request_is_current is not True:
        classification = 'AMBIGUO'
    if classification == 'POSIBLE_AUXILIO' and acoustic.available and acoustic.abrupt_change:
        classification = 'ALTA_PRIORIDAD'
    alert = classification in ('POSIBLE_AUXILIO', 'ALTA_PRIORIDAD')
    priority = 'ALTA' if classification == 'ALTA_PRIORIDAD' else 'MEDIA' if alert else '—'
    return RiskAssessment(classification, priority, alert, semantic, acoustic,
                          semantic.semantic_risk, 'CAMBIO_ABRUPTO' if acoustic.abrupt_change and acoustic.available else 'SIN_CAMBIO' if acoustic.available else 'NO_DISPONIBLE', semantic.context_change)
