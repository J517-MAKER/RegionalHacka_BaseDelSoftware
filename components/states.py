from nicegui import ui


def EmptyState(message='No hay registros para los filtros seleccionados.'):
    with ui.column().classes('empty-state items-center gap-2'):
        ui.icon('inbox',size='26px')
        ui.label(message).classes('text-sm')


def ErrorState(message,retry=None):
    with ui.row().classes('notice items-center'):
        ui.icon('error_outline')
        ui.label(message)
        if retry:
            ui.button('Reintentar',on_click=retry).props('flat')


def LoadingState(message='Cargando información…'):
    with ui.row().classes('items-center p-6'):
        ui.spinner(size='20px')
        ui.label(message)
