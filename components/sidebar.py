from nicegui import ui

NAVIGATION = [('Centro de monitoreo','/monitor','space_dashboard'),('Casos de búsqueda','/cases','folder_open'),
              ('Cámaras','/cameras','videocam'),('Reconocimiento en vivo','/live','face'),('Coincidencias','/matches','compare'),
              ('Mapa y seguimiento','/tracking','route'),('Alertas de auxilio','/alerts','notifications_none'),
              ('Comandos de voz','/voice','mic_none'),('Historial','/history','history'),
              ('Usuarios y permisos','/users','people_outline'),('Configuración','/settings','tune')]


def Sidebar(active):
    with ui.left_drawer(value=None, fixed=True, top_corner=True).props('width=226 breakpoint=1024').classes('sidebar') as drawer:
        with ui.row().classes('brand items-center w-full'):
            with ui.element('div').classes('brand-mark'):
                ui.icon('location_searching',size='23px')
            with ui.column().classes('gap-0'):
                ui.label('NEXO').classes('brand-name')
                ui.label('BÚSQUEDA Y MONITOREO').classes('brand-caption')
        ui.label('OPERACIÓN').classes('nav-heading')
        for label,path,icon in NAVIGATION:
            if path=='/users':
                ui.label('ADMINISTRACIÓN').classes('nav-heading')
            with ui.link(target=path).classes('nav-link '+('active' if active==path else '')):
                ui.icon(icon)
                ui.label(label)
        with ui.element('div').classes('sidebar-footer'):
            ui.label('ENTORNO DE DEMOSTRACIÓN').classes('text-[9px] tracking-widest')
            ui.label('Región Centro · Unidad 01')
            ui.label('Datos ficticios / acceso de prueba').classes('text-[10px]')
    return drawer
