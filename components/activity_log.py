from nicegui import ui
from components.states import EmptyState


def ActivityLog(logs,limit=5):
    if not logs:
        EmptyState('Todavía no hay actividad.')
    for entry in logs[:limit]:
        with ui.element('div').classes('activity-row'):
            ui.element('span').classes('activity-dot').style('background:#b4544c' if entry.kind=='Voz' else '')
            with ui.column().classes('gap-0'):
                ui.label(entry.description).classes('activity-text')
                ui.label(f'{entry.timestamp[11:]}  ·  {entry.camera_id if entry.camera_id!="—" else entry.user}').classes('activity-meta mono')
