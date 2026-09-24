from nicegui import ui
from components.layout import PageLayout,Panel,guard_page
from components.camera_feed import CameraFeed
from components.voice_console import MonitoringConsole
from services.camera_monitor_service import monitor
from services.cameras_service import evidence_summary, get_camera
from services.evidence_service import get_event
from services.voice_service import get_voice_events


RESULT_LABELS = {'NORMAL': 'NORMAL', 'AMBIGUO': 'AMBIGUO',
                 'POSIBLE_AUXILIO': 'POSIBLE_AUXILIO', 'ALTA_PRIORIDAD': 'ALTA_PRIORIDAD'}
STATE_LABELS = {'SIN_ALERTA': 'SIN_EVENTO', 'REQUIERE_MAS_CONTEXTO': 'SIN_EVENTO'}


@ui.page('/voice')
def voice_page():
    if not guard_page('/voice', 'voice.monitor'):
        return
    with PageLayout('/voice', 'Detección de auxilio en cámara',
                    'La cámara escucha mientras graba. Al oír una posible solicitud de auxilio conserva '
                    'el mismo instante en imagen, audio y video. La detección no confirma la existencia '
                    'de un delito.'):
        @ui.refreshable
        def events():
            rows = []
            for v in get_voice_events()[:50]:
                evidence = get_event(v.evidence_id) if v.evidence_id else None
                rows.append({'id': v.id, 'event_id': evidence.event_id if evidence else '',
                             'time': v.timestamp, 'camera': v.camera_id, 'text': v.text_original,
                             'result': RESULT_LABELS.get(v.classification, v.classification),
                             'state': STATE_LABELS.get(v.status, v.status),
                             'evidence': f'{evidence.event_id} · {evidence_summary(evidence)}' if evidence
                             else 'Sin evidencia: el audio se descartó'})
            table = ui.table(columns=[{'name': k, 'field': k, 'label': v, 'align': 'left'} for k, v in
                                      [('time', 'Hora'), ('camera', 'Cámara'), ('text', 'Transcripción'),
                                       ('result', 'Resultado'), ('state', 'Estado'),
                                       ('evidence', 'Evidencia conservada')]],
                             rows=rows, row_key='id', pagination=6).classes('w-full')
            # Abrir la fila lleva a la evidencia de ese mismo instante: video, audio y fotos.
            table.on('rowClick', lambda e: e.args[1]['event_id']
                     and ui.navigate.to(f'/alerts?event_id={e.args[1]["event_id"]}'))

        @ui.refreshable
        def camera_tile():
            camera = get_camera(monitor.audio_session().camera_id)
            if not camera:
                return
            CameraFeed(camera, lambda camera_id: ui.navigate.to(f'/cameras?camera_id={camera_id}'))
            ui.label('Esta es la cámara que escucha. Lo que se detecte aquí queda grabado en su propio '
                     'video, con el audio sincronizado.').classes('text-xs muted mt-2')

        with ui.element('div').classes('workspace-grid'):
            with ui.column().classes('panel p-6 gap-2 w-full min-w-0'):
                MonitoringConsole(on_event=events.refresh)
            with ui.element('div').classes('stack'):
                with Panel('Cámara que escucha', 'IMAGEN + AUDIO'):
                    with ui.column().classes('p-4 w-full gap-2'):
                        camera_tile()

        with Panel('Historial reciente'):
            with ui.column().classes('p-4 w-full gap-2'):
                events()
                ui.label('Las conversaciones ordinarias sólo permanecen en memoria temporal y se eliminan '
                         'automáticamente. Sólo los eventos con evidencia se conservan en /alerts.').classes('text-xs muted')
        ui.timer(5, events.refresh)
        ui.timer(10, camera_tile.refresh)
