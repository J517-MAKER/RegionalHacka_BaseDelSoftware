from nicegui import ui
from components.layout import PageLayout,Panel,guard_page
from components.voice_console import MonitoringConsole
from services.voice_service import get_voice_events


RESULT_LABELS = {'NORMAL': 'NORMAL', 'AMBIGUO': 'AMBIGUO',
                 'POSIBLE_AUXILIO': 'POSIBLE_AUXILIO', 'ALTA_PRIORIDAD': 'ALTA_PRIORIDAD'}
STATE_LABELS = {'SIN_ALERTA': 'SIN_EVENTO', 'REQUIERE_MAS_CONTEXTO': 'SIN_EVENTO'}


@ui.page('/voice')
def voice_page():
    if not guard_page('/voice', 'voice.monitor'):
        return
    with PageLayout('/voice', 'Detección de auxilio por voz',
                    'El sistema escucha audio real. La detección no confirma la existencia de un delito.'):
        @ui.refreshable
        def events():
            rows = [{'id': v.id, 'time': v.timestamp, 'camera': v.camera_id, 'text': v.text_original,
                     'result': RESULT_LABELS.get(v.classification, v.classification),
                     'state': STATE_LABELS.get(v.status, v.status)} for v in get_voice_events()[:50]]
            ui.table(columns=[{'name': k, 'field': k, 'label': v, 'align': 'left'} for k, v in
                              [('time', 'Hora'), ('camera', 'Cámara'), ('text', 'Transcripción'),
                               ('result', 'Resultado'), ('state', 'Estado')]],
                     rows=rows, row_key='id', pagination=6).classes('w-full')

        with ui.column().classes('panel p-6 gap-2 w-full'):
            MonitoringConsole(on_event=events.refresh)

        with Panel('Historial reciente'):
            with ui.column().classes('p-4 w-full gap-2'):
                events()
                ui.label('Las conversaciones ordinarias sólo permanecen en memoria temporal y se eliminan '
                         'automáticamente. Sólo los eventos con evidencia se conservan en /alerts.').classes('text-xs muted')
        ui.timer(5, events.refresh)
