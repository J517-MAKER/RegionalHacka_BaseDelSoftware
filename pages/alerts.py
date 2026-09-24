from nicegui import ui
from components.layout import PageLayout, Panel, notify_action
from components.alert_table import EvidenceTable
from components.person_profile import InfoPair
from components.status_badge import StatusBadge
from components.states import EmptyState
from services.alerts_service import start_alert_tracking
from services.cameras_service import get_camera, get_nearby_cameras
from services.evidence_service import (get_deletion_requests, get_evidence, get_event, register_playback,
                                       request_deletion, resolve_deletion, review_event, verify_integrity)
from services import store
from services.users_service import can

REVIEW_BUTTONS = [('CONFIRMAR PARA ATENCIÓN', 'CONFIRMADO_PARA_ATENCION', 'Evento confirmado para atención.'),
                  ('MARCAR FALSO POSITIVO', 'FALSO_POSITIVO', 'Marcado como falso positivo. La evidencia permanece.'),
                  ('ENVIAR A REVISIÓN', 'EN_REVISION', 'Evento enviado a revisión.')]


@ui.page('/alerts')
def alerts_page(status:str=''):
    with PageLayout('/alerts', 'Revisión de evidencia',
                    'Eventos de voz para evaluación de una autoridad. La detección no confirma la existencia de un delito.'):
        selected = {'id': None}

        with ui.right_drawer(value=False).props('width=460 bordered overlay').classes('p-0') as drawer:
            @ui.refreshable
            def detail():
                event = get_event(selected['id'])
                if not event:
                    return
                camera = get_camera(event.camera_id)
                with ui.row().classes('panel-heading w-full'):
                    ui.label(event.event_id).classes('section-title')
                    ui.button(icon='close', on_click=drawer.hide).props('flat dense round')
                with ui.column().classes('p-5 w-full gap-3'):
                    StatusBadge(event.review_status)
                    ui.label(f'{event.camera_id} — {event.location}').classes('text-sm')
                    ui.label(event.created_at).classes('text-xs muted')
                    InfoPair('Clasificación IA', event.classification)
                    InfoPair('Prioridad', event.priority)
                    ui.label('Transcripción').classes('section-title mt-2')
                    ui.label(f'“{event.transcript_original}”').classes('text-lg p-4 bg-[#f5f7f8] w-full')

                    ui.label('EVIDENCIA').classes('eyebrow mt-3')
                    player = ui.audio(f'/evidence/audio/{event.event_id}.wav').classes('w-full')
                    player.on('play', lambda: notify_action(lambda: register_playback(event.event_id),
                                                            'Reproducción registrada en la bitácora.'))
                    InfoPair('Duración', f'{event.audio_duration:.0f} segundos')
                    InfoPair('Integridad', '✓ Archivo original verificado' if verify_integrity(event)
                             else '⚠ No fue posible verificar el archivo original')
                    InfoPair('SHA-256', event.integrity_hash[:32] + '…')
                    InfoPair('Video', 'Pendiente de integración' if event.video_status == 'PENDING_INTEGRATION'
                             else event.video_file or '—')
                    if event.face_captures:
                        ui.label('Rostros en cámara al momento del evento').classes('section-title mt-2')
                        with ui.row().classes('gap-3 flex-wrap'):
                            for face in event.face_captures:
                                with ui.column().classes('gap-1 items-center'):
                                    ui.image(face['capture']).classes('w-20 h-24').props('fit=cover')
                                    if face['case_id']:
                                        ui.link(f'{face["case_id"]} · {face["similarity"]} %',
                                                f'/cases/{face["case_id"]}').classes('text-[10px]')
                                    else:
                                        ui.label('Sin coincidencia').classes('text-[10px] muted')

                    ui.label('ANÁLISIS').classes('eyebrow mt-3')
                    semantic, acoustic = event.semantic_analysis, event.acoustic_analysis
                    InfoPair('Contexto', 'Cambio significativo' if semantic.get('context_change') else 'Sin cambio relevante')
                    InfoPair('Lenguaje', semantic.get('reason', '—'))
                    InfoPair('Audio', 'Cambio acústico significativo' if acoustic.get('abrupt_change')
                             else 'Variación acústica moderada' if acoustic.get('available')
                             else 'Sin análisis acústico disponible')
                    InfoPair('Modo de análisis', semantic.get('mode', '—'))
                    for signal in semantic.get('signals', []):
                        ui.label('• ' + signal).classes('text-xs')

                    ui.label('Cámaras cercanas').classes('section-title mt-2')
                    for nearby in get_nearby_cameras(camera.id):
                        ui.link(f'{nearby.id} · {nearby.name}', f'/cameras?camera_id={nearby.id}').classes('text-xs')

                    def changed():
                        table.refresh()
                        detail.refresh()
                        requests.refresh()

                    ui.label('REVISIÓN').classes('eyebrow mt-3')
                    with ui.row().classes('gap-2 flex-wrap'):
                        for label, status, message in REVIEW_BUTTONS:
                            ui.button(label, on_click=lambda s=status, m=message:
                                      notify_action(lambda: review_event(event.event_id, s), m, changed)
                                      ).props('outline no-caps').set_enabled(can('review'))
                        ui.button('SOLICITAR ELIMINACIÓN', icon='gavel',
                                  on_click=lambda: deletion_dialog(event.event_id, changed)
                                  ).props('flat no-caps').set_enabled(can('deletion.request'))
                    ui.label('Marcar un falso positivo no elimina evidencia. La eliminación requiere autorización '
                             'de un supervisor distinto a quien la solicita.').classes('text-xs muted')
                    alert = next((a for a in store.alerts if a.voice_event_id == event.voice_event_id), None)
                    if alert:
                        ui.button('Iniciar seguimiento', icon='route',
                                  on_click=lambda: notify_action(lambda: start_alert_tracking(alert.id),
                                                                 'Seguimiento solicitado. Módulo de seguimiento pendiente de integración.',
                                                                 changed)).props('unelevated no-caps').set_enabled(can('track'))
                    if event.reviewed_by:
                        ui.label(f'{event.reviewed_by} · {event.reviewed_at}').classes('text-xs muted')
            detail()

        def deletion_dialog(event_id, changed):
            with ui.dialog() as dialog, ui.card().classes('w-96 p-6'):
                ui.label('Solicitud de eliminación').classes('section-title')
                ui.label('La evidencia permanece intacta hasta que un supervisor autorice la solicitud.').classes('text-xs muted')
                reason = ui.textarea('Motivo de la solicitud').props('outlined').classes('w-full')
                with ui.row():
                    ui.button('Cancelar', on_click=dialog.close).props('flat no-caps')

                    def send():
                        def action():
                            request_deletion(event_id, reason.value)
                            dialog.close()
                        notify_action(action, 'Solicitud enviada para autorización.', changed)
                    ui.button('Enviar solicitud', on_click=send).props('unelevated no-caps')
            dialog.open()

        def select(event_id):
            selected['id'] = event_id
            detail.refresh()
            drawer.show()

        @ui.refreshable
        def table():
            rows = [e for e in get_evidence() if state.value == 'Todos' or e.review_status == state.value]
            if query.value:
                text = query.value.lower()
                rows = [e for e in rows if text in (e.transcript_original + ' ' + e.camera_id).lower()]
            EvidenceTable(rows, select)

        @ui.refreshable
        def requests():
            if not can('deletion.approve'):
                return
            with Panel('Solicitudes de eliminación', 'SUPERVISIÓN'):
                with ui.column().classes('p-4 w-full gap-2'):
                    pending = get_deletion_requests()
                    if not pending:
                        EmptyState('No hay solicitudes de eliminación registradas.')
                    for item in pending:
                        with ui.row().classes('items-center justify-between w-full border-b border-[#edf0f2] py-2'):
                            with ui.column().classes('gap-0'):
                                ui.label(f'{item.event_id} · {item.request_id}').classes('text-sm font-medium')
                                ui.label(f'Solicitado por {item.requested_by} · {item.requested_at}').classes('text-xs muted')
                                ui.label(f'Motivo: {item.reason}').classes('text-xs')
                                if item.reviewed_by:
                                    ui.label(f'{item.status} por {item.reviewed_by} · {item.reviewed_at}').classes('text-xs muted')
                            if item.status == 'PENDING':
                                def resolve(request_id=item.request_id, approve=True):
                                    notify_action(lambda: resolve_deletion(request_id, approve),
                                                  'Solicitud aprobada. El archivo original se conserva y queda registrada la operación.'
                                                  if approve else 'Solicitud rechazada. La evidencia permanece.',
                                                  lambda: (table.refresh(), detail.refresh(), requests.refresh()))
                                with ui.row().classes('gap-2'):
                                    ui.button('APROBAR', on_click=lambda r=item.request_id: resolve(r, True)).props('outline no-caps')
                                    ui.button('RECHAZAR', on_click=lambda r=item.request_id: resolve(r, False)).props('flat no-caps')
                            else:
                                StatusBadge(item.status)

        with ui.element('div').classes('toolbar'):
            query = ui.input('Buscar cámara o frase', on_change=lambda: table.refresh()).props('outlined dense clearable')
            state = ui.select(['Todos', 'PENDIENTE_REVISION', 'EN_REVISION', 'CONFIRMADO_PARA_ATENCION',
                               'FALSO_POSITIVO', 'DELETION_REQUESTED', 'DELETION_APPROVED', 'DELETION_REJECTED'],
                              value=status or 'Todos', label='Estado', on_change=lambda: table.refresh()).props('outlined dense')
            ui.button('Actualizar', icon='refresh', on_click=lambda: table.refresh()).props('outline no-caps')
        table()
        requests()
        ui.timer(10, table.refresh)
