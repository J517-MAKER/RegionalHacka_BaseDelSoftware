"""Document preview, extracted photo and match blocks for the alert import page."""
from nicegui import ui
from components.states import EmptyState

EXTRACTION_LABELS = {
    'PENDIENTE': 'Pendiente de análisis',
    'EXTRACCION_COMPLETA': 'Extracción completa',
    'EXTRACCION_PARCIAL': 'Extracción parcial · revisa los campos vacíos',
    'SIN_TEXTO_RECONOCIDO': 'Sin texto reconocido · captura manual',
    'REVISADA_POR_OPERADOR': 'Revisada por el operador',
}
LEVEL_CLASS = {'ALTA': 'red', 'MEDIA': 'amber', 'BAJA': 'blue'}


def DocumentPreview(record):
    with ui.column().classes('w-full gap-2'):
        if record and record.preview_path:
            ui.image('/' + record.preview_path).classes('w-full border border-[#dce2e7]').props('fit=contain')
            ui.label(f'Archivo: {record.source_file.rsplit("/", 1)[-1]} · {record.source_type}').classes('text-xs muted')
        else:
            EmptyState('Aún no se ha cargado ninguna ficha.')


def ExtractedPhoto(record):
    with ui.column().classes('w-full gap-2 items-start'):
        if record and record.photo_path:
            ui.image('/' + record.photo_path).classes('w-40 border border-[#dce2e7]').props('fit=contain')
        else:
            with ui.column().classes('w-40 h-48 border border-dashed border-[#dce2e7] items-center justify-center'):
                ui.icon('person_off', size='26px', color='blue-grey-4')
                ui.label('Sin fotografía').classes('text-xs muted')
        if record:
            ui.label(record.extraction_notes or '').classes('text-xs muted')
            ui.label('Recorte automático orientativo. Puede sustituirse antes de crear el caso.').classes('text-xs muted')


def ExtractionStatus(record):
    if not record:
        return
    status = EXTRACTION_LABELS.get(record.extraction_status, record.extraction_status)
    with ui.row().classes('items-center gap-3'):
        ui.label('Estado de extracción:').classes('text-xs muted')
        ui.label(status).classes('text-sm font-medium')
        if record.ocr_engine:
            ui.label(f'Lectura: {record.ocr_engine}').classes('text-xs muted')


def MatchLevel(level, text, detail=''):
    with ui.row().classes('items-start gap-3 w-full border-b border-[#edf0f2] py-2'):
        with ui.element('span').classes(f'badge {LEVEL_CLASS.get(level, "")}'):
            ui.element('span').classes('status-dot')
            ui.label(level)
        with ui.column().classes('gap-0 flex-1 min-w-0'):
            ui.label(text).classes('text-sm')
            if detail:
                ui.label(detail).classes('text-xs muted')


def MatchBlocks(record, on_link=None):
    """Three groups, always phrased as possibilities pending human validation."""
    ui.label('Coincidencias con casos existentes').classes('section-title')
    if record.text_matches:
        for match in record.text_matches:
            with ui.row().classes('items-center gap-3 w-full'):
                MatchLevel(match['level'], f'{match["case_id"]} — {match["label"]}',
                           f'{match["name"]} · ' + ', '.join(match['reasons']))
                if on_link:
                    ui.button('Vincular', on_click=lambda case_id=match['case_id']: on_link(case_id)) \
                        .props('flat dense no-caps')
    else:
        ui.label('Sin coincidencias textuales suficientes con los casos registrados.').classes('text-sm muted')

    ui.label('Coincidencias faciales').classes('section-title mt-3')
    if record.face_reference_status == 'COINCIDENCIAS_FACIALES':
        for match in record.face_matches:
            with ui.row().classes('items-center gap-3 w-full'):
                MatchLevel(match['level'], f'{match["case_id"]} — {match["label"]}',
                           f'{match["name"]} · similitud {match["percent"]} %')
                if on_link:
                    ui.button('Vincular', on_click=lambda case_id=match['case_id']: on_link(case_id)) \
                        .props('flat dense no-caps')
        ui.label(record.face_message).classes('text-xs muted')
    elif record.face_reference_status == 'PENDIENTE_MODULO_FACIAL':
        ui.label('Referencia facial preparada. La comparación la realizará el módulo de reconocimiento '
                 'facial cuando esté integrado; aquí no se asignan niveles automáticos.').classes('text-sm')
        if record.face_matches:
            ui.label('Cámaras que recibirán la referencia: '
                     + ', '.join(item['camera_id'] for item in record.face_matches)).classes('text-xs muted')
    elif record.face_reference_status == 'SIN_FOTOGRAFIA':
        ui.label('No hay fotografía recortada; no se preparó una referencia facial.').classes('text-sm muted')
    elif record.face_message:  # sin coincidencias, sin rostro detectable o motor no disponible
        ui.label(record.face_message).classes('text-sm muted')
    else:
        ui.label('Pendiente de análisis.').classes('text-sm muted')

    ui.label('Coincidencias contextuales').classes('section-title mt-3')
    for match in record.context_matches or []:
        MatchLevel(match['level'], match['text'], match['kind'])
    if not record.context_matches:
        ui.label('Pendiente de análisis.').classes('text-sm muted')
    ui.label('Ningún resultado confirma una identidad ni una localización. Todo queda pendiente de '
             'validación humana.').classes('text-xs muted mt-2')
