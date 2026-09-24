"""Candidato a revisión: señales independientes, nunca una probabilidad de identidad.

El motor no dice "es esta persona". Dice qué señales son compatibles y con qué fuerza, y
deja la decisión a un operador y después a un supervisor. Por eso las señales se guardan
por separado y la puntuación combinada se llama prioridad de revisión, no certeza.
"""
from dataclasses import dataclass, field

# Un candidato nace de la IA y sólo avanza por decisión de personas.
CANDIDATE_STATES = ('AI_CANDIDATE', 'PENDING_HUMAN_REVIEW', 'OPERATOR_ACCEPTED_FOR_REVIEW',
                    'OPERATOR_REJECTED', 'SUPERVISOR_VALIDATED', 'SUPERVISOR_REJECTED')
STATE_LABELS = {'AI_CANDIDATE': 'Candidato generado',
                'PENDING_HUMAN_REVIEW': 'Pendiente de revisión',
                'OPERATOR_ACCEPTED_FOR_REVIEW': 'Enviado a supervisión',
                'OPERATOR_REJECTED': 'Descartado por operador',
                'SUPERVISOR_VALIDATED': 'Validado para investigación',
                'SUPERVISOR_REJECTED': 'Rechazado por supervisión'}

# Niveles cualitativos. NO_EVALUABLE no penaliza: significa que no había con qué comparar.
SIGNAL_LEVELS = ('ALTA', 'MEDIA', 'BAJA', 'NO_EVALUABLE')
SIGNAL_LABELS = {'face': 'Similitud facial', 'temporal': 'Compatibilidad temporal',
                 'geographic': 'Compatibilidad geográfica', 'appearance': 'Rasgos visibles',
                 'route': 'Continuidad de ruta'}
# De dónde salió la captura comparada.
CAPTURE_KINDS = {'EVENTO': 'Persona vista en un evento de auxilio',
                 'DETECCION': 'Detección de una cámara',
                 'CAPTURA_BD': 'Captura registrada en la base de datos'}


@dataclass
class MatchSignal:
    level: str = 'NO_EVALUABLE'
    detail: str = 'Sin información suficiente para comparar.'
    score: float | None = None


@dataclass
class CandidateMatch:
    candidate_match_id: str
    case_id: str
    profile_id: str
    camera_id: str
    timestamp: str
    location: str = ''

    detection_id: str = ''
    person_candidate_id: str = ''
    event_id: str = ''
    frame_path: str = ''
    face_image_path: str = ''

    signals: dict = field(default_factory=dict)
    # Rasgos estimados de la captura (edad aparente, color de la ropa) y su origen, para la
    # tabla de características frente a lo que declara la ficha.
    capture_kind: str = 'DETECCION'
    capture_attributes: dict = field(default_factory=dict)
    # Orden de revisión, no probabilidad de que sea la persona.
    relevance_score: float = 0.0
    outcome: str = 'CANDIDATO'
    temporal_window: str = 'EN_RANGO_PRIORITARIO'
    linked_to_distress_event: bool = False

    status: str = 'PENDING_HUMAN_REVIEW'
    reviewed_by: str = ''
    reviewed_at: str = ''
    review_notes: str = ''
    supervised_by: str = ''
    supervised_at: str = ''
    disclosure_status: str = 'INTERNAL_ONLY'
    created_at: str = ''

    def signal(self, name):
        return self.signals.get(name, MatchSignal())
