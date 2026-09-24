"""Comparación lado a lado: la ficha de búsqueda frente a la persona que vio una cámara.

Muestra lo que una persona necesita para decidir: las dos imágenes, cuánto se parecen los
rostros, cada característica de la ficha frente a lo que se estimó en la cámara, y el contexto
(tiempo desde la desaparición y distancia al último lugar conocido). El parecido facial se
presenta como lo que es —una medida entre dos rostros— y nunca como la probabilidad de que sea
la misma persona: la identidad sólo la confirma una revisión humana.
"""
from nicegui import ui
from components.status_badge import StatusBadge
from models.candidate_match import CAPTURE_KINDS, STATE_LABELS, MatchSignal
from services.appearance_service import age_compatibility, clothing_compatibility

LEVEL_BADGE = {'ALTA': 'green', 'MEDIA': 'amber', 'BAJA': 'blue', 'NO_EVALUABLE': ''}
LEVEL_TEXT = {'ALTA': 'ALTA', 'MEDIA': 'MEDIA', 'BAJA': 'BAJA', 'NO_EVALUABLE': 'NO EVALUABLE'}
METER_COLORS = {'ALTA': 'positive', 'MEDIA': 'warning', 'BAJA': 'orange', None: 'grey'}


def clean(name):
    return (name or '').replace(' (ficticia)', '').replace(' (ficticio)', '')


def LevelBadge(level):
    with ui.element('span').classes(f'badge {LEVEL_BADGE.get(level, "")}'):
        ui.element('span').classes('status-dot')
        ui.label(LEVEL_TEXT.get(level, level or '—'))


def SimilarityMeter(value, level):
    """Cuánto se parecen los dos rostros según el modelo, en una barra con su nivel."""
    value = max(0.0, min(1.0, float(value or 0)))
    with ui.column().classes('w-full gap-1 face-meter'):
        with ui.row().classes('items-center justify-between w-full'):
            ui.label('PARECIDO FACIAL').classes('eyebrow')
            with ui.row().classes('items-center gap-2'):
                ui.label(f'{value:.0%}').classes('text-lg font-semibold').mark('face-similarity')
                LevelBadge(level or 'NO_EVALUABLE')
        ui.linear_progress(value=value, show_value=False, size='10px', color=METER_COLORS.get(level, 'grey')) \
            .props('rounded track-color=grey-3')
        ui.label('Mide cuánto se parecen los dos rostros según el modelo facial. No es la probabilidad de '
                 'que se trate de la misma persona.').classes('text-[10px] muted')


def ficha_side(case=None, profile=None, photo=None):
    """Lo que declara la ficha, desde un caso registrado o una referencia sin caso."""
    person = case.person if case else None
    return {'photo': photo or (profile.reference_photo if profile and profile.reference_photo else None)
                     or (person.photos[0] if person and person.photos else '/assets/demo/person-1.svg'),
            'name': clean(person.name) if person else (profile.official_folio if profile else 'Referencia'),
            'folio': case.id if case else 'Sin caso registrado',
            'age': (person.age if person else (profile.declared_age if profile else '')) or '',
            'missing': (f'{case.missing_date} · {case.missing_time}' if case else
                        (profile.disappearance_datetime if profile else '')) or 'Sin fecha declarada',
            'location': (case.location if case else (profile.last_known_location if profile else '')) or '—',
            'clothing': (person.clothing if person else (profile.clothing_description if profile else '')) or '',
            'marks': (person.marks if person else (profile.distinctive_marks if profile else '')) or '',
            'build': (f'{person.height} · {person.build} · cabello {person.hair}' if person else
                      (profile.physical_description if profile else '')) or ''}


def capture_side(image, camera=None, timestamp='', kind='DETECCION', estimated_age=None, clothing_color=None,
                 label=''):
    return {'image': image or '/assets/demo/capture.svg',
            'camera': f'{camera.id} · {camera.name}' if camera else '—',
            'timestamp': timestamp or '—', 'kind': CAPTURE_KINDS.get(kind, kind), 'label': label,
            'estimated_age': estimated_age, 'clothing_color': clothing_color}


def _row(label, declared, observed, level, detail):
    with ui.element('div').classes('trait-row'):
        ui.label(label).classes('trait-name')
        ui.label(declared or '—').classes('trait-value')
        ui.label(observed or '—').classes('trait-value')
        with ui.column().classes('gap-1'):
            LevelBadge(level)
            if detail:
                ui.label(detail).classes('text-[10px] muted leading-tight')


def TraitTable(ficha, capture, signals):
    """Cada característica de la ficha frente a lo que se estimó de la captura."""
    signals = signals or {}
    age_level, age_detail = age_compatibility(ficha['age'], capture['estimated_age'])
    cloth_level, cloth_detail = clothing_compatibility(ficha['clothing'], capture['clothing_color'])
    temporal = signals.get('temporal', MatchSignal())
    geographic = signals.get('geographic', MatchSignal())
    route = signals.get('route', MatchSignal())
    ui.label('CARACTERÍSTICAS: FICHA FRENTE A CÁMARA').classes('eyebrow mt-3')
    with ui.element('div').classes('trait-table'):
        with ui.element('div').classes('trait-row trait-head'):
            for title in ('Característica', 'Ficha (declarado)', 'Cámara (estimado)', 'Compatibilidad'):
                ui.label(title)
        _row('Edad', f'{ficha["age"]} años' if str(ficha['age']).strip().isdigit() else ficha['age'],
             f'~{capture["estimated_age"]} años' if capture['estimated_age'] is not None else 'No estimada',
             age_level, age_detail)
        _row('Vestimenta', ficha['clothing'],
             f'Ropa superior {capture["clothing_color"]}' if capture['clothing_color'] else 'No visible',
             cloth_level, cloth_detail)
        _row('Fecha', f'Desaparición: {ficha["missing"]}', f'Captura: {capture["timestamp"]}',
             temporal.level, temporal.detail)
        _row('Lugar', f'Último lugar conocido: {ficha["location"]}', capture['camera'],
             geographic.level, geographic.detail)
        _row('Continuidad', '—', 'Otras apariciones cercanas', route.level, route.detail)
    if ficha['marks'] and 'Sin' not in ficha['marks']:
        ui.label(f'Señas particulares declaradas: {ficha["marks"]} — verifícalas en la imagen.') \
            .classes('text-[11px] mt-1')


def FaceComparison(ficha, capture, signals, priority=None, note=None):
    """Las dos imágenes, el parecido facial, las características y el contexto."""
    face = (signals or {}).get('face', MatchSignal())
    with ui.element('div').classes('comparison-images w-full'):
        with ui.column().classes('gap-1'):
            ui.label('FICHA DE BÚSQUEDA').classes('comparison-label')
            ui.image(ficha['photo']).props('fit=contain')
            ui.label(ficha['name']).classes('text-sm font-medium')
            ui.label(ficha['folio']).classes('mono muted')
        with ui.column().classes('gap-1'):
            ui.label('PERSONA VISTA POR LA CÁMARA').classes('comparison-label')
            ui.image(capture['image']).props('fit=contain')
            ui.label(capture['camera']).classes('text-sm font-medium')
            ui.label(f'{capture["timestamp"]} · {capture["kind"]}').classes('text-[11px] muted')
    if face.score is not None:
        SimilarityMeter(face.score, face.level)
    else:
        ui.label('Sin huella facial comparable: el parecido de los rostros no pudo medirse.').classes('notice')
    TraitTable(ficha, capture, signals)
    if priority:
        with ui.row().classes('items-center gap-2 mt-3'):
            ui.label('Prioridad de revisión').classes('text-xs muted')
            LevelBadge(priority)
    ui.label(note or 'IDENTIDAD NO CONFIRMADA. El sistema propone a quién revisar; no afirma quién es. '
                     'La información es interna y no se comunica a terceros.').classes('notice mt-2')


def candidate_sides(candidate):
    """(ficha, captura) de un candidato del motor de búsqueda."""
    from services.cameras_service import get_camera
    from services.cases_service import get_case
    from services.search_matching_service import get_profile
    case, profile = get_case(candidate.case_id), get_profile(candidate.case_id)
    attributes = candidate.capture_attributes or {}
    return (ficha_side(case, profile),
            capture_side(candidate.face_image_path, get_camera(candidate.camera_id), candidate.timestamp,
                         candidate.capture_kind, attributes.get('estimated_age'), attributes.get('clothing_color'),
                         attributes.get('label', '')))


def CandidateSummaryRow(candidate, on_change=None):
    """Fila compacta con las dos miniaturas; abre la comparación completa en un diálogo."""
    from services.search_matching_service import priority_level
    ficha, capture = candidate_sides(candidate)
    face = candidate.signal('face')
    with ui.row().classes('items-center gap-3 w-full border-b border-[#edf0f2] py-2 no-wrap'):
        ui.image(ficha['photo']).classes('w-12 h-14 rounded shrink-0').props('fit=cover')
        ui.icon('compare_arrows', size='16px', color='blue-grey-4')
        ui.image(capture['image']).classes('w-12 h-14 rounded shrink-0').props('fit=cover')
        with ui.column().classes('gap-0 flex-1 min-w-0'):
            ui.label(f'{candidate.case_id} · {ficha["name"]}').classes('text-xs font-medium')
            ui.label(f'{candidate.camera_id} · {candidate.timestamp}').classes('text-[10px] muted')
            with ui.row().classes('items-center gap-2'):
                ui.label('Rostro').classes('text-[10px] muted')
                LevelBadge(face.level)
                ui.label('Prioridad').classes('text-[10px] muted')
                LevelBadge(priority_level(candidate.relevance_score))
        ui.button('Comparar', icon='compare', on_click=lambda: open_candidate_dialog(candidate, on_change)) \
            .props('flat dense no-caps')


def open_candidate_dialog(candidate, on_change=None):
    from components.candidate_review import CandidateReview
    with ui.dialog() as dialog, ui.card().classes('app-dialog wide p-0 gap-0'):
        with ui.row().classes('panel-heading w-full'):
            ui.label(f'{candidate.candidate_match_id} · {STATE_LABELS.get(candidate.status, candidate.status)}') \
                .classes('section-title')
            ui.button(icon='close', on_click=dialog.close).props('flat dense round')
        with ui.column().classes('p-5 w-full gap-0'):
            def changed():
                dialog.close()
                if on_change:
                    on_change()
            CandidateReview(candidate, on_change=changed)
    dialog.open()
    return dialog


__all__ = ['FaceComparison', 'SimilarityMeter', 'TraitTable', 'CandidateSummaryRow', 'LevelBadge',
           'ficha_side', 'capture_side', 'candidate_sides', 'open_candidate_dialog', 'StatusBadge']
