import time
from nicegui import ui
from components.status_badge import StatusBadge
from services.cameras_service import camera_listening_state, evidence_summary, recent_camera_evidence
from services.live_recognition_service import get_live_for_camera, is_live_camera


def ListeningChip(camera):
    """Lo que el micrófono de esta cámara está oyendo, sobre la propia imagen.

    La detección de auxilio no es una pantalla aparte: la cámara escucha mientras graba, así que
    su estado se lee aquí, junto al video, y no en otro módulo.
    """
    with ui.element('span').classes('camera-listen') as chip:
        icon = ui.icon('mic', size='11px')
        text = ui.label('ESCUCHANDO')

    def update():
        state = camera_listening_state(camera.id)
        chip.set_visibility(state['analyzed'])
        if not state['analyzed']:
            return
        text.set_text(state['state'])
        icon.props(f'name={"mic" if state["listening"] else "mic_off"}')
        chip.classes(replace='camera-listen ' + ('on' if state['listening'] else 'off'))
    update()
    return update


def EventNotice(camera):
    """Aviso sobre la imagen cuando esta cámara acaba de conservar evidencia de un auxilio.

    Es el vínculo que faltaba: lo que se escuchó quedó grabado en esta cámara, y desde aquí se
    abre para que una autoridad lo revise.
    """
    shown = {'id': None}
    with ui.element('div').classes('camera-event') as notice:
        headline = ui.label('')
        detail = ui.label('').classes('camera-event-detail')
    notice.set_visibility(False)

    def open_event():
        if shown['id']:
            ui.navigate.to(f'/alerts?event_id={shown["id"]}')
    notice.on('click', open_event)

    def update():
        event = recent_camera_evidence(camera.id)
        notice.set_visibility(event is not None)
        if event is None or event.event_id == shown['id']:
            shown['id'] = event.event_id if event else None
            return
        shown['id'] = event.event_id
        headline.set_text(f'AUXILIO DETECTADO · “{event.transcript_original[:60]}”')
        detail.set_text(f'{event.event_id} · {evidence_summary(event)} · toca para revisar')
    update()
    return update


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
            with ui.row().classes('items-center gap-1'):
                listening = ListeningChip(camera)
                badge = ui.label('● EN VIVO').style('background:#c62828;padding:2px 6px;border-radius:4px')
        notice = EventNotice(camera)
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
        listening()
        notice()
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
                    notice = EventNotice(camera)
                    with ui.element('div').classes('camera-bottom'):
                        ui.label('23 SEP 2026 / 10:28:04')
                        ui.icon('volume_up' if camera.audio else 'volume_off', size='13px')
                ui.timer(2, notice)
            if camera.status == 'Desconectada' and not own:
                with ui.element('div').classes('camera-offline'):
                    ui.icon('videocam_off', size='30px')
                    ui.label('Sin señal · cámara desconectada')
        with ui.element('div').classes('camera-caption'):
            ui.label(camera.name + (' · cámara del equipo' if own else ''))
            StatusBadge(camera.status)
