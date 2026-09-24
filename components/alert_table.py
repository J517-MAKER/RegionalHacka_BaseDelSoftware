from nicegui import ui
from components.states import EmptyState


def EvidenceTable(events, on_select):
    if not events:
        EmptyState('No hay evidencia registrada para los filtros seleccionados.')
        return
    rows = [{'id': e.event_id, 'time': e.created_at, 'camera': f'{e.camera_id} — {e.location}',
             'event': e.event_id, 'type': e.classification, 'priority': e.priority,
             'status': e.review_status} for e in events]
    columns = [{'name': key, 'label': label, 'field': key, 'align': 'left', 'sortable': True} for key, label in
               [('time', 'Hora'), ('camera', 'Cámara'), ('event', 'Evento'),
                ('type', 'Clasificación'), ('priority', 'Prioridad'), ('status', 'Estado')]]
    columns.append({'name': 'actions', 'label': 'Acciones', 'field': 'id', 'align': 'left'})
    table = ui.table(columns=columns, rows=rows, row_key='id', pagination=8).classes('w-full')
    table.add_slot('body-cell-actions',
                   '<q-td :props="props"><q-btn flat dense no-caps color="primary" label="Revisar" '
                   '@click="$parent.$emit(\'review\', props.row.id)" /></q-td>')
    table.on('review', lambda e: on_select(e.args))
