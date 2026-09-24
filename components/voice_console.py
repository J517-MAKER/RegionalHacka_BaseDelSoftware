"""Monitoring console: real microphone only. Nothing here is typed by the operator."""
from nicegui import ui, run
from services.cameras_service import get_cameras, get_camera
from services.camera_monitor_service import monitor
from services.monitoring_service import microphone_available
from services.users_service import can, require
import config


def MonitoringConsole(on_event=None):
    # Sesión compartida del monitoreo continuo: esta página la observa, no la posee.
    session = monitor.audio_session()
    state = {'busy': False, 'shown': None, 'error': None}

    with ui.row().classes('items-center justify-between w-full'):
        with ui.column().classes('gap-0'):
            ui.label('SERVICIO DE DETECCIÓN').classes('eyebrow')
            with ui.row().classes('items-center gap-2'):
                dot = ui.element('span').classes('status-dot')
                status = ui.label('DETENIDO').classes('text-lg font-medium')
        with ui.column().classes('gap-0 items-end'):
            microphone = ui.label('Micrófono: comprobando…').classes('text-xs muted')
            ui.label('Idioma: Español · Transcripción local').classes('text-xs muted')

    with ui.row().classes('items-end gap-4 w-full mt-2'):
        camera = ui.select({c.id: f'{c.id} — {c.name}' for c in get_cameras()},
                           value=config.DEFAULT_CAMERA_ID, label='Cámara').props('outlined dense').classes('w-72')
        location = ui.label('').classes('text-xs muted pb-2')
    level = ui.linear_progress(value=0, show_value=False).classes('w-full')

    def describe_camera():
        selected = get_camera(camera.value)
        location.set_text(selected.location if selected else '')
    camera.on_value_change(describe_camera)
    describe_camera()

    @ui.refreshable
    def analysis():
        result = state['shown']
        if not result:
            ui.label('Sin análisis todavía. Inicia el monitoreo y conversa con normalidad.').classes('text-sm muted')
            return
        ui.label('TRANSCRIPCIÓN').classes('eyebrow')
        ui.label(f'“{result["transcript"]}”').classes('text-lg p-4 bg-[#f5f7f8] w-full')
        ui.label('ANÁLISIS').classes('eyebrow mt-2')
        ui.label(result['headline']).classes('text-base font-medium')
        with ui.row().classes('gap-6'):
            ui.label(f'Resultado: {result["classification"]}').classes('text-sm')
            ui.label(f'Prioridad: {result["priority"]}').classes('text-sm')
        ui.label('Señales').classes('section-title mt-2')
        for signal in result['signals']:
            ui.label('• ' + signal).classes('text-sm')
        ui.label('RESULTADO').classes('eyebrow mt-2')
        ui.label(result['outcome']).classes('text-sm whitespace-pre-wrap')
        if result['event_id']:
            ui.button('Revisar evidencia', icon='fact_check',
                      on_click=lambda: ui.navigate.to('/alerts')).props('unelevated no-caps').classes('mt-2')

    def controls():
        start_button.set_enabled(not session.running and can('voice.monitor'))
        stop_button.set_enabled(session.running and can('voice.monitor'))
        camera.set_enabled(not session.running)

    async def start():
        if state['busy']:
            return
        state['busy'] = True
        try:
            actor = require('voice.monitor')
            await run.io_bound(monitor.resume_audio, actor, camera.value)
            ui.notify('Detección reanudada. El audio ordinario no se almacena.', type='positive', position='bottom-right')
        except Exception as exc:
            ui.notify(str(exc), type='warning', position='bottom-right')
        finally:
            state['busy'] = False
            controls()

    async def stop():
        if state['busy']:
            return
        state['busy'] = True
        try:
            actor = require('voice.monitor')
            # Una pausa deliberada se respeta: el monitoreo no reabre el micrófono solo.
            await run.io_bound(monitor.pause_audio, actor)
            ui.notify('Detección pausada. El audio temporal fue descartado.', type='info', position='bottom-right')
        finally:
            state['busy'] = False
            controls()

    with ui.row().classes('gap-3 mt-3'):
        start_button = ui.button('REANUDAR DETECCIÓN', icon='play_arrow', on_click=start).props('unelevated no-caps').mark('monitor-start')
        stop_button = ui.button('PAUSAR DETECCIÓN', icon='pause', on_click=stop).props('outline no-caps').mark('monitor-stop')
    hint = ui.label('').classes('text-xs muted mt-1')
    ui.label('Esta cámara escucha de forma continua desde que arranca NEXO: no depende de que '
             'alguien inicie la detección.').classes('notice')
    ui.label('Audio en vivo. El sistema conserva únicamente los segundos alrededor de una posible solicitud '
             'de auxilio; el resto se sobrescribe en memoria.').classes('text-xs muted mt-1')

    with ui.column().classes('w-full gap-1 mt-4'):
        analysis()
    controls()

    def refresh():
        audio = monitor.audio_state()  # no llamarlo `state`: taparía el del componente
        status.set_text(session.status if session.running else audio['state'])
        hint.set_text(audio['detail'])
        dot.classes(replace='status-dot ' + ('green' if session.running else ''))
        level.set_value(session.level if session.running else 0)
        if session.error and session.error != state['error']:
            state['error'] = session.error
            ui.notify(session.error, type='warning', position='bottom-right')
        latest = session.results[0] if session.results else None
        if latest is not state['shown']:
            state['shown'] = latest
            analysis.refresh()
            if on_event:
                on_event()
        controls()
    ui.timer(.5, refresh)

    async def probe():
        available = await run.io_bound(microphone_available)
        microphone.set_text('Micrófono: Disponible' if available else 'Micrófono: No disponible')
    ui.timer(.1, probe, once=True)

    return session
