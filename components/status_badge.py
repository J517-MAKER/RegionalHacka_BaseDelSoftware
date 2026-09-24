from nicegui import ui


def StatusBadge(text):
    color = ('red' if text in ('Alerta','Posible solicitud de auxilio') else
             'green' if text in ('En línea','Activo','Validada por operador','Evento confirmado por operador') else
             'amber' if any(word in text.lower() for word in ('pendiente','revisión','posible')) else
             'blue' if text in ('En búsqueda','Seguimiento iniciado') else '')
    with ui.element('span').classes(f'badge {color}'):
        ui.element('span').classes('status-dot')
        ui.label(text)
