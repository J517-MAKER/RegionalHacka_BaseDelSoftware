"""Push-to-talk assistant for administrators. Independent of the distress detection."""
from nicegui import app, ui, run
from services.admin_voice_assistant_service import handle_command
from services.users_service import can, require
from services.voice_service import MicrophoneCapture, transcribe_audio

STATES = {'IDLE': ('mic', 'Asistente de voz', 'Toca para hablar'),
          'LISTENING': ('stop', 'Escuchando...', 'Toca nuevamente para detener'),
          'PROCESSING': ('more_horiz', 'Procesando...', 'Interpretando el comando'),
          'SUCCESS': ('check', 'Listo', ''),
          'ERROR': ('priority_high', 'Sin resultado', '')}


def AdminVoiceAssistant():
    """Added once by the shared layout; hidden and inoperative for other roles."""
    notice = app.storage.user.pop('assistant_notice', None)
    if notice:
        ui.timer(.1, lambda: ui.notify(notice, type='positive', position='bottom-right', timeout=3500), once=True)
    if not can('assistant'):
        return None
    capture = MicrophoneCapture()
    state = {'name': 'IDLE', 'busy': False}

    with ui.element('div').classes('assistant-dock'):
        panel = ui.element('div').classes('assistant-panel')
        with panel:
            ui.label('Asistente').classes('assistant-title')
            status = ui.label('Toca para hablar').classes('assistant-status')
            transcript = ui.label('').classes('assistant-transcript')
            outcome = ui.label('').classes('assistant-outcome')
            options = ui.column().classes('assistant-options')
            hint = ui.label('').classes('assistant-hint')
        panel.set_visibility(False)
        button = ui.button(icon='mic', on_click=lambda: toggle()).props('round unelevated') \
            .classes('assistant-button').mark('assistant-button')
        button.tooltip('Asistente de voz · sólo administradores')

    def render(name, message=None, said='', result='', choices=()):
        state['name'] = name
        icon, label, tip = STATES[name]
        button.props(f'icon={icon}')
        button.classes(remove='listening processing done failed',
                       add={'LISTENING': 'listening', 'PROCESSING': 'processing',
                            'SUCCESS': 'done', 'ERROR': 'failed'}.get(name, ''))
        status.set_text(message or label)
        status.classes(replace='assistant-status ' + ('live' if name == 'LISTENING' else ''))
        transcript.set_text(f'“{said}”' if said else '')
        transcript.set_visibility(bool(said))
        outcome.set_text(result)
        outcome.set_visibility(bool(result))
        hint.set_text(tip)
        hint.set_visibility(bool(tip))
        options.clear()
        with options:
            for choice in choices:
                with ui.element('div').classes('assistant-option').on(
                        'click', lambda route=choice['route'], text=choice['label']: open_route(route, text)):
                    ui.label(choice['label']).classes('text-xs font-medium')
                    ui.label(choice['sublabel']).classes('mono muted')
        options.set_visibility(bool(choices))
        panel.set_visibility(name != 'IDLE')

    def open_route(route, message):
        app.storage.user['assistant_notice'] = message
        ui.navigate.to(route)

    def reset():
        if state['name'] in ('SUCCESS', 'ERROR') and not state['busy']:
            render('IDLE')

    async def begin():
        try:
            require('assistant')
            await run.io_bound(capture.start)
            render('LISTENING')
        except Exception as exc:
            render('ERROR', result=str(exc))
            ui.timer(5, reset, once=True)

    async def finish():
        render('PROCESSING')
        audio = None
        try:
            actor = require('assistant')  # resolved here: the worker thread has no session
            audio = await run.io_bound(capture.stop)
            said, _ = await run.io_bound(transcribe_audio, audio)
            result = await run.io_bound(handle_command, said, actor)
            if result['status'] == 'OPTIONS':
                render('SUCCESS', message=result['message'], said=said, choices=result['options'])
            elif result['status'] == 'SUCCESS':
                detail = f'✓ {result["message"]}' + (f'\n{result["detail"]}' if result['detail'] else '')
                render('SUCCESS', said=said, result=detail)
                if result['route']:
                    ui.timer(1.2, lambda: open_route(result['route'], result['message']), once=True)
            else:
                render('ERROR', said=said, result=result['message'])
        except Exception as exc:
            render('ERROR', result=str(exc))
        finally:
            audio = None  # the command audio is never stored nor reused
            capture.chunks.clear()
            ui.timer(5, reset, once=True)

    async def toggle():
        if state['busy']:
            return
        state['busy'] = True
        try:
            if state['name'] == 'LISTENING':
                await finish()
            else:
                await begin()
        finally:
            state['busy'] = False

    async def cleanup():
        await run.io_bound(capture.close)
    ui.context.client.on_disconnect(cleanup)
    return button
