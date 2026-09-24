"""Perfil de búsqueda: lo que la ficha oficial afirma, listo para comparar.

Importar una ficha y buscar son dos pasos distintos. El perfil se crea cuando un operador
confirmó la fotografía y corrigió los datos del OCR; sólo entonces puede compararse contra
las detecciones almacenadas. Los campos que la ficha no dice quedan vacíos, nunca inventados.
"""
from dataclasses import dataclass, field

SEARCH_STATES = ('SIN_INICIAR', 'BUSCANDO', 'CON_CANDIDATOS', 'SIN_CANDIDATOS', 'PAUSADA')


@dataclass
class SearchProfile:
    profile_id: str
    case_id: str
    created_at: str
    created_by: str

    official_folio: str = ''
    reference_photo: str = ''
    face_embedding: list = field(default_factory=list)
    face_status: str = 'PENDIENTE'
    face_message: str = ''

    # Momento desde el que las detecciones son prioritarias. Nada se descarta por ser anterior.
    disappearance_datetime: str = ''
    disappearance_time_known: bool = False
    report_datetime: str = ''
    last_known_location: str = ''
    last_known_camera_id: str = ''
    # Coordenadas aproximadas del último lugar conocido, si el texto se pudo situar sin
    # conexión (una cámara de la red o un lugar del catálogo local). Nunca se inventan.
    last_known_lat: float | None = None
    last_known_lng: float | None = None
    last_known_place: str = ''

    # Descriptores tal como los declara la ficha, no inferidos de ninguna imagen.
    declared_age: str = ''
    physical_description: str = ''
    distinctive_marks: str = ''
    clothing_description: str = ''
    # Huella de las fotografías con las que se calculó la referencia facial: si cambian, se recalcula.
    reference_signature: str = ''

    search_start_datetime: str = ''
    search_status: str = 'SIN_INICIAR'
    # Todo resultado nace interno; comunicarlo fuera exigiría una autorización aparte.
    disclosure_status: str = 'INTERNAL_ONLY'
    notes: str = ''
