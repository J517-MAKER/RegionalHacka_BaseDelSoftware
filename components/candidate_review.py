"""Revisión de un candidato: ficha a la izquierda, persona de la cámara a la derecha.

Debajo, cuánto se parecen los rostros y cada característica de la ficha frente a lo que se
estimó en la cámara, con el contexto de fecha y lugar. No se muestra un porcentaje de
identidad: un número único —«93 % es Carlos»— sugiere una certeza que el sistema no tiene. El
parecido facial se presenta como una medida entre dos rostros, y el resultado se llama
prioridad de revisión.
"""
from nicegui import ui
from components.face_comparison import FaceComparison, candidate_sides
from components.layout import notify_action
from components.status_badge import StatusBadge
from models.candidate_match import SIGNAL_LABELS, STATE_LABELS
from services.search_matching_service import operator_review, priority_level, supervisor_review
from services.users_service import can

LEVEL_CLASSES = {'ALTA': 'signal-high', 'MEDIA': 'signal-medium',
                 'BAJA': 'signal-low', 'NO_EVALUABLE': 'signal-none'}
LEVEL_LABELS = {'ALTA': 'ALTA', 'MEDIA': 'MEDIA', 'BAJA': 'BAJA', 'NO_EVALUABLE': 'NO EVALUABLE'}


def SignalGrid(candidate):
    ui.label('EVIDENCIAS DE COMPATIBILIDAD').classes('eyebrow mt-3')
    with ui.element('div').classes('signal-grid'):
        for name, label in SIGNAL_LABELS.items():
            signal = candidate.signal(name)
            with ui.element('div').classes('signal-item'):
                ui.label(label).classes('signal-name')
                ui.label(LEVEL_LABELS.get(signal.level, signal.level)).classes(
                    'signal-level ' + LEVEL_CLASSES.get(signal.level, 'signal-none'))
                ui.label(signal.detail).classes('signal-detail')


def ContextNotices(candidate):
    if candidate.temporal_window == 'FUERA_DEL_RANGO_PRIORITARIO':
        ui.label('Detección anterior a la desaparición. Se conserva porque puede ayudar a reconstruir '
                 'la trayectoria previa, pero no es prioritaria.').classes('notice mt-2')
    if candidate.linked_to_distress_event:
        with ui.row().classes('notice mt-2 items-center justify-between'):
            ui.label(f'Asociado al evento de auxilio {candidate.event_id}. Es contexto del evento: no '
                     'significa que esta persona sea la víctima.').classes('flex-1')
            if can('alerts.view'):
                ui.button('Ver evidencia', icon='videocam',
                          on_click=lambda: ui.navigate.to(f'/alerts?event_id={candidate.event_id}')) \
                    .props('flat dense no-caps')


def CandidateReview(candidate, on_change=None, supervising=False):
    """Un candidato con sus dos lados y las acciones que el rol permite."""
    with ui.row().classes('items-center justify-between w-full mb-3'):
        with ui.column().classes('gap-1'):
            ui.label(candidate.outcome).classes('text-lg font-medium')
            ui.label(f'{candidate.candidate_match_id} / {candidate.case_id}').classes('mono muted')
        StatusBadge(STATE_LABELS.get(candidate.status, candidate.status))

    ficha, capture = candidate_sides(candidate)
    FaceComparison(ficha, capture, candidate.signals, priority=priority_level(candidate.relevance_score))
    ContextNotices(candidate)
    with ui.expansion('Detalle de cada señal').classes('w-full mt-2'):
        SignalGrid(candidate)

    with ui.row().classes('gap-2 mt-4 flex-wrap'):
        if supervising and can('matches.supervise') and candidate.status == 'OPERATOR_ACCEPTED_FOR_REVIEW':
            ui.button('VALIDAR PARA INVESTIGACIÓN',
                      on_click=lambda: notify_action(
                          lambda: supervisor_review(candidate.candidate_match_id, True),
                          'Candidato validado para investigación. La identidad no queda confirmada.',
                          on_change)).props('unelevated no-caps')
            ui.button('RECHAZAR COINCIDENCIA',
                      on_click=lambda: notify_action(
                          lambda: supervisor_review(candidate.candidate_match_id, False),
                          'Candidato rechazado.', on_change)).props('outline no-caps')
        elif can('matches.review') and candidate.status in ('AI_CANDIDATE', 'PENDING_HUMAN_REVIEW'):
            # Un operador nunca confirma una persona: sólo descarta o escala.
            ui.button('ENVIAR A SUPERVISIÓN',
                      on_click=lambda: notify_action(
                          lambda: operator_review(candidate.candidate_match_id, True),
                          'Candidato enviado a supervisión.', on_change)).props('unelevated no-caps')
            ui.button('DESCARTAR',
                      on_click=lambda: notify_action(
                          lambda: operator_review(candidate.candidate_match_id, False),
                          'Candidato descartado.', on_change)).props('outline no-caps')
        ui.button('Ver trayectoria', on_click=lambda: ui.navigate.to(f'/tracking?case_id={candidate.case_id}')
                  ).props('flat no-caps')

    if candidate.reviewed_by:
        ui.label(f'Revisión del operador: {candidate.reviewed_by} · {candidate.reviewed_at}').classes('text-xs muted mt-2')
    if candidate.supervised_by:
        ui.label(f'Supervisión: {candidate.supervised_by} · {candidate.supervised_at} · '
                 f'{candidate.disclosure_status}').classes('text-xs muted')


def CandidateRow(candidate, on_open=None):
    """Fila compacta para listados."""
    with ui.row().classes('items-center justify-between w-full border-b border-[#edf0f2] py-2'):
        with ui.column().classes('gap-0 min-w-0'):
            ui.label(f'{candidate.camera_id} · {candidate.timestamp}').classes('text-sm font-medium')
            ui.label(f'{candidate.case_id} · {candidate.candidate_match_id}').classes('mono muted')
            levels = ' · '.join(f'{SIGNAL_LABELS[n]}: {LEVEL_LABELS.get(candidate.signal(n).level, "—")}'
                                for n in ('face', 'temporal', 'geographic'))
            ui.label(levels).classes('text-xs muted')
        with ui.row().classes('items-center gap-2'):
            StatusBadge(STATE_LABELS.get(candidate.status, candidate.status))
            if on_open:
                ui.button('REVISAR', icon='open_in_new',
                          on_click=lambda c=candidate: on_open(c)).props('outline dense no-caps')
