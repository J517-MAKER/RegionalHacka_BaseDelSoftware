import time
from nicegui import ui
from components.status_badge import StatusBadge
from services.live_recognition_service import get_live_for_camera, is_live_camera


def LiveStage(camera):
    """The webcam of this computer: live frames while recognition runs, a clear idle state otherwise."""
    video = ui.interactive_image().classes('w-full h-full live-tile-video')
    with ui.element('div').classes('camera-offline') as idle:
        ui.icon('videocam_off', size='30px')
        ui.label('Cámara del equipo detenida')
        ui.label('Enciéndela en Reconocimiento en vivo').classes('text-[10px]')
    with ui.element('div').classes('camera-overlay'):
        with ui.element('div').classes('camera-top'):
            ui.label(camera.id)
            badge = ui.label('● EN VIVO').style('background:#c62828;padding:2px 6px;border-radius:4px')
        with ui.element('div').classes('camera-bottom'):
            inst = get_live_for_camera(camera.id)
            tag = f'{inst.name} · {inst.device_name}' if inst and inst.device_name else inst.name if inst else 'CÁMARA DEL EQUIPO'
            ui.label(tag)
            ui.icon('volume_up' if camera.audio else 'volume_off', size='13px')

    def update():
        inst = get_live_for_camera(camera.id)
        running = inst is not None and inst.running
        video.set_visibility(running)
        idle.set_visibility(not running)
        badge.set_visibility(running)
        if running:
            video.set_source(f'/live/frame/{camera.id}.jpg?{time.time()}')
    update()
    ui.timer(.2, update)


def CameraFeed(camera, on_select=None):
    own = is_live_camera(camera.id)  # local camera on this computer
    with ui.element('div').classes('camera-tile ' + ('event' if camera.status in ('Alerta', 'Posible coincidencia') else '')).props('tabindex=0 role=button') as tile:
        if on_select:
            tile.on('click', lambda: on_select(camera.id))
            tile.on('keydown.enter', lambda: on_select(camera.id))
        with ui.element('div').classes('camera-stage'):
            if own:
                LiveStage(camera)
            else:
                ui.image(f'/assets/demo/cctv-{int(camera.id[-3:])%3+1}.svg').props('no-spinner')
                with ui.element('div').classes('camera-overlay'):
                    with ui.element('div').classes('camera-top'):
                        ui.label(camera.id)
                        ui.label('REPRODUCCIÓN DEMO')
                    with ui.element('div').classes('camera-bottom'):
                        ui.label('23 SEP 2026 / 10:28:04')
                        ui.icon('volume_up' if camera.audio else 'volume_off', size='13px')
            if camera.status == 'Desconectada' and not own:
                with ui.element('div').classes('camera-offline'):
                    ui.icon('videocam_off', size='30px')
                    ui.label('Sin señal · cámara desconectada')
        with ui.element('div').classes('camera-caption'):
            ui.label(camera.name + (' · cámara del equipo' if own else ''))
            StatusBadge(camera.status)
