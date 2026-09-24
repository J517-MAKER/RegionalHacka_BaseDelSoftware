"""Supervision inbox: what operators escalated and what needs authorisation.

A work tray, not a dashboard. Every row opens the operational context it refers to, so a
second review is made with the case, the camera and the evidence at hand.
"""
from nicegui import ui
from components.layout import PageLayout, Panel, guard_page, notify_action
from components.candidate_review import CandidateReview, CandidateRow
from components.states import EmptyState
from components.status_badge import StatusBadge
from services.evidence_service import get_deletion_requests, get_evidence, resolve_deletion
from services.facial_service import get_detection, get_matches
from services.search_matching_service import get_candidates
from services.users_service import can


def _escalated():
    """Matches and evidence an operator sent to a second review."""
    rows = []
    for match in get_matches():
        if match.status != 'En revisión':
            continue
        detection = get_detection(match.detection_id)
        rows.append({'kind': 'Coincidencia', 'event': match.id,
                     'context': f'{detection.case_id} · {detection.camera_id}' if detection else '—',
                     'actor': match.reviewed_by or 'Operación', 'when': match.reviewed_at or '—',
                     'status': match.status,
                     'route': f'/matches?match_id={match.id}&review=En revisión'})
    for event in get_evidence():
        if event.review_status != 'EN_REVISION':
            continue
        rows.append({'kind': 'Evidencia', 'event': event.event_id,
                     'context': f'{event.camera_id} · {event.location}',
                     'actor': event.reviewed_by or 'Operación', 'when': event.reviewed_at or event.created_at,
                     'status': event.review_status,
                     'route': f'/alerts?status=EN_REVISION'})
    return rows


@ui.page('/supervision')
def supervision_page(focus: str = ''):
    if not guard_page('/supervision', 'supervision.view'):
        return
    with PageLayout('/supervision', 'Centro de supervisión',
                    'Elementos escalados por operadores que requieren una segunda revisión.'):
        @ui.refreshable
        def tray():
            escalated, requests = _escalated(), get_deletion_requests()
            pending = [r for r in requests if r.status == 'PENDING']
            with ui.element('div').classes('stat-strip'):
                for value, label, detail in [(len(escalated), 'Pendientes de revisión', 'Escalados por operadores'),
                                             (len(pending), 'Solicitudes de eliminación', 'Esperan autorización')]:
                    with ui.element('div').classes('stat-item'):
                        ui.label(str(value)).classes('stat-value')
                        with ui.column().classes('gap-0'):
                            ui.label(label).classes('stat-label')
                            ui.label(detail).classes('stat-detail')

            if focus != 'deletions':
                escalated_candidates = get_candidates(status='OPERATOR_ACCEPTED_FOR_REVIEW')
                if escalated_candidates:
                    with Panel('Candidatos enviados por operadores',
                               f'{len(escalated_candidates)} PARA VALIDAR O RECHAZAR'):
                        with ui.column().classes('p-4 w-full gap-2'):
                            for candidate in escalated_candidates:
                                CandidateRow(candidate, on_open=open_candidate)
                            ui.label('Validar significa que la coincidencia es relevante para la '
                                     'investigación. No confirma legalmente la identidad de nadie.'
                                     ).classes('text-xs muted')
                with Panel('Pendientes de revisión', 'COINCIDENCIAS Y EVIDENCIA ESCALADAS'):
                    with ui.column().classes('p-4 w-full gap-2'):
                        if not escalated:
                            EmptyState('No hay elementos escalados pendientes de revisión.')
                        for row in escalated:
                            with ui.row().classes('items-center justify-between w-full border-b border-[#edf0f2] py-2'):
                                with ui.column().classes('gap-0 min-w-0'):
                                    ui.label(f'{row["kind"]} · {row["event"]}').classes('text-sm font-medium')
                                    ui.label(row['context']).classes('mono muted')
                                    ui.label(f'Enviado por {row["actor"]} · {row["when"]}').classes('text-xs muted')
                                with ui.row().classes('items-center gap-2'):
                                    StatusBadge(row['status'])
                                    ui.button('Revisar', icon='open_in_new',
                                              on_click=lambda r=row['route']: ui.navigate.to(r)
                                              ).props('outline dense no-caps')

            with Panel('Solicitudes de eliminación', 'AUTORIZACIÓN DE SUPERVISIÓN'):
                with ui.column().classes('p-4 w-full gap-2'):
                    if not requests:
                        EmptyState('No hay solicitudes de eliminación registradas.')
                    for item in requests:
                        with ui.row().classes('items-center justify-between w-full border-b border-[#edf0f2] py-2'):
                            with ui.column().classes('gap-0 min-w-0'):
                                ui.label(f'{item.event_id} · {item.request_id}').classes('text-sm font-medium')
                                ui.label(f'Solicitado por {item.requested_by} · {item.requested_at}').classes('text-xs muted')
                                ui.label(f'Motivo: {item.reason}').classes('text-xs')
                                if item.reviewed_by:
                                    ui.label(f'{item.status} por {item.reviewed_by} · {item.reviewed_at}').classes('text-xs muted')
                            if item.status == 'PENDING' and can('deletion.approve'):
                                def resolve(request_id, approve):
                                    notify_action(lambda: resolve_deletion(request_id, approve),
                                                  'Solicitud aprobada. El archivo original se conserva y queda registrada la operación.'
                                                  if approve else 'Solicitud rechazada. La evidencia permanece.',
                                                  tray.refresh)
                                with ui.row().classes('gap-2'):
                                    ui.button('APROBAR', on_click=lambda r=item.request_id: resolve(r, True)).props('outline no-caps')
                                    ui.button('RECHAZAR', on_click=lambda r=item.request_id: resolve(r, False)).props('flat no-caps')
                            else:
                                StatusBadge(item.status)
                    ui.label('Aprobar marca la evidencia como autorizada para eliminación y conserva el archivo '
                             'original. Quien solicita no puede autorizar su propia solicitud.').classes('text-xs muted')
        selected = {'id': None}

        def open_candidate(candidate):
            selected['id'] = candidate.candidate_match_id
            candidate_detail.refresh()
            drawer.show()

        with ui.right_drawer(value=False).props('width=560 bordered overlay').classes('p-0') as drawer:
            @ui.refreshable
            def candidate_detail():
                from services.search_matching_service import get_candidate
                candidate = get_candidate(selected['id'])
                if not candidate:
                    return
                with ui.row().classes('panel-heading w-full'):
                    ui.label(candidate.candidate_match_id).classes('section-title')
                    ui.button(icon='close', on_click=drawer.hide).props('flat dense round')
                with ui.column().classes('p-5 w-full gap-0'):
                    CandidateReview(candidate, on_change=lambda: (candidate_detail.refresh(), tray.refresh()),
                                    supervising=True)
            candidate_detail()
        tray()
