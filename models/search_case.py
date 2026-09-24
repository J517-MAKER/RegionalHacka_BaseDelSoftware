from dataclasses import dataclass
from models.person import Person


@dataclass
class SearchCase:
    id: str
    person: Person
    missing_date: str
    reported_at: str
    location: str
    zone: str
    owner: str
    status: str = 'En búsqueda'
    missing_time: str = 'Desconocida'
    reference_status: str = 'Pendiente de procesamiento'
