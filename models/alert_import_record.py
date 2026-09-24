"""Alert imported from a search poster. Every field is a reading proposal, never a fact."""
from dataclasses import dataclass, field

EDITABLE_FIELDS = [
    ('person_name', 'Nombre completo'),
    ('folio', 'Folio o identificador de la alerta'),
    ('age', 'Edad'),
    ('sex_reported', 'Sexo o género reportado'),
    ('nationality', 'Nacionalidad'),
    ('date_of_disappearance', 'Fecha de desaparición o de los hechos'),
    ('date_of_report', 'Fecha del reporte'),
    ('location_of_events', 'Lugar de desaparición o de los hechos'),
    ('physical_description', 'Descripción física (complexión, estatura, tez)'),
    ('distinctive_marks', 'Señas particulares'),
    ('clothing_description', 'Vestimenta'),
    ('authority', 'Autoridad emisora'),
    ('investigation_file', 'Carpeta de investigación'),
]

LONG_FIELDS = {'physical_description', 'distinctive_marks', 'clothing_description', 'location_of_events'}


@dataclass
class AlertImportRecord:
    id: str
    source_file: str = ''
    source_type: str = ''
    imported_at: str = ''
    imported_by: str = ''

    person_name: str | None = None
    folio: str | None = None
    age: str | None = None
    sex_reported: str | None = None
    nationality: str | None = None
    date_of_disappearance: str | None = None
    date_of_report: str | None = None
    location_of_events: str | None = None
    physical_description: str | None = None
    distinctive_marks: str | None = None
    clothing_description: str | None = None
    authority: str | None = None
    investigation_file: str | None = None

    preview_path: str = ''
    photo_path: str = ''
    ocr_text: str = ''
    ocr_engine: str = ''
    extraction_status: str = 'PENDIENTE'
    extraction_notes: str = ''

    face_reference_status: str = 'PENDIENTE'
    face_message: str = ''
    text_match_status: str = 'PENDIENTE'
    context_match_status: str = 'PENDIENTE'

    face_matches: list = field(default_factory=list)
    text_matches: list = field(default_factory=list)
    context_matches: list = field(default_factory=list)
    # La ficha contra lo que las cámaras ya guardaron (eventos, detecciones, base compartida).
    camera_matches: list = field(default_factory=list)
    camera_match_status: str = 'PENDIENTE'
    reference_profile: object = None

    linked_case_id: str | None = None
    review_status: str = 'PENDIENTE_VALIDACION'
    review_notes: str = ''

    def as_case_data(self):
        """Prefills the existing case form; unknown values stay empty, never invented."""
        return {'name': self.person_name or '', 'age': self.age or '', 'sex': self.sex_reported or '',
                'missing_date': self.date_of_disappearance or '', 'location': self.location_of_events or '',
                'build': self.physical_description or '', 'marks': self.distinctive_marks or '',
                'clothing': self.clothing_description or '',
                'description': ' · '.join(part for part in
                                          (f'Importado de alerta {self.folio}' if self.folio else 'Importado de alerta',
                                           self.authority, self.investigation_file) if part)}
