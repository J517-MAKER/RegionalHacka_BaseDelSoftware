from urllib.parse import parse_qsl, urlsplit
from nicegui import ui
from services.users_service import can, can_any

# Navigation is derived from permissions, not from the role name. Each group belongs to one
# responsibility, so a session only ever sees the tools of the job it performs.
NAV_GROUPS = [
    ('OPERACIÓN', ('monitor.view',), [
        ('Centro de monitoreo','/monitor','space_dashboard','monitor.view'),
        ('Casos de búsqueda','/cases','folder_open','cases.view'),
        ('Búsqueda por ficha','/search','person_search','cases.import'),
        ('Cámaras','/cameras','videocam','cameras.view'),
        ('Reconocimiento en vivo','/live','face','live.view'),
        ('Coincidencias','/matches','compare','matches.view'),
        ('Mapa y seguimiento','/tracking','route','tracking.view'),
        ('Alertas de auxilio','/alerts','notifications_none','alerts.view'),
        # /voice is the automatic microphone monitoring; the administrative spoken
        # commands live only in the NEXO assistant.
        ('Detección de auxilio','/voice','mic_none','voice.monitor'),
        ('Historial operativo','/history','history','history.operational')]),
    ('SUPERVISIÓN', ('supervision.view',), [
        ('Bandeja de supervisión','/supervision','inbox','supervision.view'),
        ('Evidencia en revisión','/alerts?status=EN_REVISION','fact_check','alerts.view'),
        ('Coincidencias en revisión','/matches?review=En revisión','compare','matches.supervise'),
        ('Solicitudes de eliminación','/supervision?focus=deletions','gavel','deletion.approve'),
        ('Auditoría operativa','/history','history','audit.operational')]),
    ('ADMINISTRACIÓN', ('users.manage','settings.manage','audit.full'), [
        ('Usuarios y permisos','/users','people_outline','users.manage'),
        ('Configuración','/settings','tune','settings.manage'),
        ('Auditoría completa','/history','history','audit.full')]),
]


def _key(target):
    """Path plus decoded query, so '/supervision?focus=deletions' and '/supervision' differ
    and a percent-encoded query still matches the literal one written above."""
    parts = urlsplit(target)
    return parts.path, tuple(sorted(parse_qsl(parts.query)))


def _current_key():
    try:
        url = ui.context.client.request.url
        return _key(url.path + ('?' + url.query if url.query else ''))
    except Exception:
        return None  # no request context: fall back to matching the page's own path


def _active_index(entries, active):
    """Exact target wins; otherwise the first entry on that path without a query does."""
    current = _current_key()
    if current:
        for index, entry in enumerate(entries):
            if _key(entry[1]) == current:
                return index
    for index, entry in enumerate(entries):
        if entry[1] == active:
            return index
    for index, entry in enumerate(entries):
        if entry[1].split('?')[0] == active:
            return index
    return None


def Sidebar(active):
    with ui.left_drawer(value=None, fixed=True, top_corner=True).props('width=226 breakpoint=1024').classes('sidebar') as drawer:
        with ui.row().classes('brand items-center w-full'):
            with ui.element('div').classes('brand-mark'):
                ui.icon('location_searching',size='23px')
            with ui.column().classes('gap-0'):
                ui.label('NEXO').classes('brand-name')
                ui.label('BÚSQUEDA Y MONITOREO').classes('brand-caption')
        groups = [(heading,[e for e in entries if can(e[3])])
                  for heading,group_permissions,entries in NAV_GROUPS if can_any(*group_permissions)]
        groups = [(heading,allowed) for heading,allowed in groups if allowed]  # no empty headings
        # Several entries share a page and differ only by their query, so the highlight is
        # resolved once over every visible entry instead of per group.
        visible = [entry for _,allowed in groups for entry in allowed]
        active_entry = _active_index(visible,active)
        position = 0
        for heading,allowed in groups:
            ui.label(heading).classes('nav-heading')
            for label,target,icon,_ in allowed:
                current = position==active_entry
                position += 1
                with ui.link(target=target).classes('nav-link '+('active' if current else '')):
                    ui.icon(icon)
                    ui.label(label)
        with ui.element('div').classes('sidebar-footer'):
            ui.label('ENTORNO DE DEMOSTRACIÓN').classes('text-[9px] tracking-widest')
            ui.label('Región Centro · Unidad 01')
            ui.label('Datos ficticios / acceso de prueba').classes('text-[10px]')
    return drawer
