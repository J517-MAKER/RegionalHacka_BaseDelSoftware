from nicegui import ui
from components.layout import PageLayout, guard_page
from components.camera_grid import CameraGrid
from components.camera_feed import CameraFeed
from components.status_badge import StatusBadge
from components.person_profile import InfoPair
from components.states import EmptyState
from services.cameras_service import get_cameras, get_camera, get_nearby_cameras, get_camera_events
from services.live_recognition_service import is_live_camera, get_live_for_camera
import config


@ui.page('/cameras')
def cameras_page(camera_id: str = ''):
    if not guard_page('/cameras', 'cameras.view'):
        return
    with PageLayout('/cameras', 'Red de cámaras', 'Vistas de prueba de la red distribuida. Selecciona una cámara para consultar su información.'):
        with ui.right_drawer(value=False).props('width=370 bordered overlay').classes('p-0') as drawer:
            detail = ui.column().classes('w-full gap-0')

        def open_camera(cid):
            camera = get_camera(cid)
            if not camera:
                return
            detail.clear()
            with detail:
                with ui.row().classes('panel-heading w-full'):
                    ui.label(camera.id).classes('section-title')
                    ui.button(icon='close', on_click=drawer.hide).props('flat dense round')
                CameraFeed(camera)
                own = is_live_camera(camera.id)
                live_inst = get_live_for_camera(camera.id)
                with ui.column().classes('p-5 w-full gap-2'):
                    StatusBadge(camera.status)
                    audio = 'Micrófono del equipo · detección por voz' if camera.id in (config.DEFAULT_CAMERA_ID, config.SECOND_CAMERA_ID) else 'Disponible · simulación' if camera.audio else 'No disponible'
                    for label, value in [('Nombre', camera.name), ('Ubicación', camera.location), ('Última comunicación', camera.last_seen), ('Audio', audio)]:
                        InfoPair(label, value)
                    if own and live_inst:
                        InfoPair('Video', f'{live_inst.name}' + (f' · {live_inst.device_name}' if live_inst.device_name else '')
                                           + ' · ' + ('en vivo' if live_inst.running else 'detenida'))
                        ui.button('Abrir reconocimiento en vivo', icon='face', on_click=lambda: ui.navigate.to('/live')).props('unelevated no-caps')
                    if camera.status == 'Desconectada':
                        ui.label('Conexión perdida. No fue posible conectar con la cámara.').classes('notice')
                        ui.button('Reintentar conexión', on_click=lambda: ui.notify('No fue posible conectar con la cámara. Servicio de demostración sin señal.', type='warning')).props('outline no-caps')
                    ui.label('Eventos recientes').classes('section-title mt-3')
                    events = get_camera_events(cid)
                    for d in events:
                        ui.link(f'{d.timestamp[11:]} · {d.case_id}', f'/cases/{d.case_id}').classes('text-xs')
                    if not events:
                        ui.label('Sin detecciones registradas.').classes('text-xs muted')
                    ui.label('Cámaras cercanas').classes('section-title mt-3')
                    for nearby in get_nearby_cameras(cid):
                        ui.button(f'{nearby.id} · {nearby.name}', on_click=lambda n=nearby.id: open_camera(n)).props('flat dense no-caps')
                    ui.button('Ver en mapa', icon='map', on_click=lambda: ui.navigate.to(f'/tracking?camera_id={cid}')).props('unelevated no-caps').classes('mt-4')
            drawer.show()

        @ui.refreshable
        def grid():
            cameras = [c for c in get_cameras() if (status.value == 'Todas' or c.status == status.value) and (not search.value or search.value.lower() in (c.id + ' ' + c.name).lower())]
            # Prioritize all live equipment cameras at the top
            cameras.sort(key=lambda c: (not is_live_camera(c.id), c.id != config.DEFAULT_CAMERA_ID))
            if not cameras:
                EmptyState()
                return
            count = int(layout.value)
            start = (int(page.value) - 1) * count * count
            if start >= len(cameras):
                start = 0
                page.value = 1
            CameraGrid(cameras[start:], count, open_camera)
            ui.label(f'{min(start+1, len(cameras))}–{min(start+count*count, len(cameras))} de {len(cameras)} cámaras · {config.DEFAULT_CAMERA_ID} y {config.SECOND_CAMERA_ID} son cámaras en vivo del equipo; las demás son capturas sintéticas').classes('text-xs muted mt-3')

        with ui.element('div').classes('toolbar'):
            search = ui.input('Buscar cámara o ubicación', on_change=lambda: grid.refresh()).props('outlined dense clearable')
            status = ui.select(['Todas', 'En línea', 'Posible coincidencia', 'Alerta', 'Desconectada'], value='Todas', label='Estado', on_change=lambda: grid.refresh()).props('outlined dense')
            ui.space()
            layout = ui.toggle({2: '2 × 2', 3: '3 × 3', 4: '4 × 4'}, value=2, on_change=lambda: grid.refresh()).props('no-caps unelevated')
            page = ui.select([1, 2, 3, 4], value=1, label='Grupo', on_change=lambda: grid.refresh()).props('outlined dense').classes('max-w-24')
        grid()
        if camera_id:
            open_camera(camera_id)
