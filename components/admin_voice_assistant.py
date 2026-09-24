"""Push-to-talk assistant for administrators. Independent of the distress detection."""
from nicegui import app, ui, run
from services.admin_voice_assistant_service import TRANSCRIPTION_PROMPT, handle_command
from services.users_service import can, require
from services.voice_service import MicrophoneCapture, transcribe_audio

STATES = {'IDLE': ('mic', 'Asistente de voz', 'Toca para hablar'),
          'LISTENING': ('stop', 'Escuchando...', 'Toca nuevamente para detener'),
          'PROCESSING': ('more_horiz', 'Procesando...', 'Interpretando el comando'),
          'SUCCESS': ('check', 'Listo', ''),
          'ERROR': ('priority_high', 'Sin resultado', '')}

# Mascot drawn inline so its antenna, eyes and mouth can react to the state through CSS.
# The gradient ids carry a suffix: the drawing appears twice per page and repeated ids
# make the browser resolve the fills against the wrong (hidden) copy.
MASCOT = '''
<svg viewBox="0 0 64 64" class="mascot" aria-hidden="true">
  <defs>
    <linearGradient id="mascotShell-{tag}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="100%" stop-color="#dde8f0"/>
    </linearGradient>
    <linearGradient id="mascotFace-{tag}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#1b3d54"/>
      <stop offset="100%" stop-color="#0f2433"/>
    </linearGradient>
  </defs>
  <line x1="32" y1="9" x2="32" y2="17" stroke="#9fb4c2" stroke-width="2.4" stroke-linecap="round"/>
  <circle class="mascot-spark" cx="32" cy="7" r="3.6" fill="#5ec6f2"/>
  <rect x="6" y="27" width="6" height="12" rx="3" fill="#245f83"/>
  <rect x="52" y="27" width="6" height="12" rx="3" fill="#245f83"/>
  <rect x="12" y="16" width="40" height="34" rx="13" fill="url(#mascotShell-{tag})"
        stroke="#173c53" stroke-width="2"/>
  <rect x="17" y="21.5" width="30" height="21" rx="9.5" fill="url(#mascotFace-{tag})"/>
  <ellipse class="mascot-eye" cx="25.5" cy="31" rx="3.1" ry="3.5" fill="#7fe1ff"/>
  <ellipse class="mascot-eye" cx="38.5" cy="31" rx="3.1" ry="3.5" fill="#7fe1ff"/>
  <path class="mascot-smile" d="M27 37.2q5 3.4 10 0" stroke="#7fe1ff" stroke-width="2"
        stroke-linecap="round" fill="none"/>
  <g class="mascot-wave" fill="#7fe1ff">
    <rect x="27.2" y="35" width="2.2" height="4" rx="1.1"/>
    <rect x="30.9" y="33.4" width="2.2" height="7.2" rx="1.1"/>
    <rect x="34.6" y="35" width="2.2" height="4" rx="1.1"/>
  </g>
</svg>
'''


def AdminVoiceAssistant():
    """Added once by the shared layout; hidden and inoperative for other roles."""
    notice = app.storage.user.pop('assistant_notice', None)
    if notice:
        ui.timer(.1, lambda: ui.notify(notice, type='positive', position='bottom-right', timeout=3500), once=True)
    if not can('assistant.use'):
        return None
    capture = MicrophoneCapture()
    state = {'name': 'IDLE', 'busy': False, 'open': False}

    dock = ui.element('div').classes('assistant-dock')
    with dock:
        panel = ui.element('div').classes('assistant-panel')
        with panel:
            with ui.element('div').classes('assistant-head'):
                ui.html(MASCOT.format(tag='head')).classes('assistant-avatar')
                with ui.element('div').classes('assistant-head-text'):
                    ui.label('NEXO · Asistente').classes('assistant-name')
                    status = ui.label('Toca para hablar').classes('assistant-status')
                close = ui.button(icon='close', on_click=lambda: shut()).props('flat round dense') \
                    .classes('assistant-close')
            with ui.element('div').classes('assistant-body'):
                greeting = ui.label('Hola, soy tu asistente. Pídeme un caso, una cámara o una sección '
                                    'y te llevo ahí.').classes('assistant-greeting')
                transcript = ui.label('').classes('assistant-transcript')
                outcome = ui.label('').classes('assistant-outcome')
                options = ui.column().classes('assistant-options')
                hint = ui.label('').classes('assistant-hint')
            with ui.element('div').classes('assistant-foot'):
                talk = ui.button('Hablar', icon='mic', on_click=lambda: toggle()).props('unelevated') \
                    .classes('assistant-talk')
                # Un micrófono lejano o una sala ruidosa pueden dejar mal escrita la frase. El
                # mismo comando se puede teclear: recorre exactamente el mismo camino que la voz.
                typed = ui.input(placeholder='O escríbelo aquí') \
                    .props('dense outlined bg-color=white input-class=text-xs') \
                    .classes('assistant-typed').mark('assistant-input')
                typed.on('keydown.enter', lambda: send_typed())
        panel.set_visibility(False)
        # color=white: a flat Quasar button otherwise paints its label with the primary colour,
        # which is unreadable over the dark pill.
        button = ui.button(on_click=lambda: toggle()).props('flat no-caps color=white') \
            .classes('assistant-launcher').mark('assistant-button')
        with button:
            ui.html(MASCOT.format(tag='dock')).classes('assistant-mascot')
            with ui.element('div').classes('assistant-launcher-text'):
                ui.label('Asistente NEXO').classes('assistant-launcher-name')
                launcher_hint = ui.label('Toca para hablar').classes('assistant-launcher-hint')
        button.tooltip('Asistente de voz · sólo administradores')

    def render(name, message=None, said='', result='', choices=()):
        state['name'] = name
        icon, label, tip = STATES[name]
        dock.classes(remove='is-listening is-processing is-done is-failed',
                     add={'LISTENING': 'is-listening', 'PROCESSING': 'is-processing',
                          'SUCCESS': 'is-done', 'ERROR': 'is-failed'}.get(name, ''))
        talk.props(f'icon={icon}')
        talk.set_text({'LISTENING': 'Detener', 'PROCESSING': 'Procesando'}.get(name, 'Hablar'))
        talk.classes(remove='listening processing done failed',
                     add={'LISTENING': 'listening', 'PROCESSING': 'processing',
                          'SUCCESS': 'done', 'ERROR': 'failed'}.get(name, ''))
        status.set_text(message or label)
        status.classes(replace='assistant-status ' + ('live' if name == 'LISTENING' else ''))
        launcher_hint.set_text('Toca para hablar' if name == 'IDLE' else label)
        transcript.set_text(f'“{said}”' if said else '')
        transcript.set_visibility(bool(said))
        outcome.set_text(result)
        outcome.set_visibility(bool(result))
        hint.set_text(tip)
        hint.set_visibility(bool(tip))
        greeting.set_visibility(name == 'IDLE' and not said and not result)
        options.clear()
        with options:
            for choice in choices:
                with ui.element('div').classes('assistant-option').on(
                        'click', lambda route=choice['route'], text=choice['label']: open_route(route, text)):
                    ui.label(choice['label']).classes('text-xs font-medium')
                    ui.label(choice['sublabel']).classes('mono muted')
        options.set_visibility(bool(choices))
        close.set_enabled(name not in ('LISTENING', 'PROCESSING'))
        if name != 'IDLE':
            state['open'] = True  # any activity brings the panel forward
        panel.set_visibility(state['open'])

    def shut():
        """The X only dismisses the panel; it never leaves the microphone open behind it."""
        if state['name'] in ('LISTENING', 'PROCESSING'):
            return
        state['open'] = False
        render('IDLE')

    def open_route(route, message):
        app.storage.user['assistant_notice'] = message
        ui.navigate.to(route)

    def reset():
        if state['name'] in ('SUCCESS', 'ERROR') and not state['busy']:
            render('IDLE')

    async def begin():
        try:
            require('assistant.use')
            await run.io_bound(capture.start)
            render('LISTENING')
        except Exception as exc:
            render('ERROR', result=str(exc))
            ui.timer(5, reset, once=True)

    async def send_typed():
        """El mismo comando, tecleado. Un micrófono lejano o una sala con ruido pueden dejar la
        frase mal escrita; escribirla recorre exactamente el mismo camino que la voz."""
        if state['busy'] or not (typed.value or '').strip():
            return
        state['busy'] = True
        said = typed.value.strip()
        typed.set_value('')
        try:
            actor = require('assistant.use')
            render('PROCESSING')
            await run_command(said, actor)
        except Exception as exc:
            render('ERROR', result=str(exc))
            ui.timer(5, reset, once=True)
        finally:
            state['busy'] = False

    async def run_command(said, actor):
        """Interpreta y ejecuta un comando ya en texto, venga del micrófono o del teclado."""
        try:
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
            render('ERROR', said=said, result=str(exc))
        finally:
            ui.timer(5, reset, once=True)

    async def finish():
        render('PROCESSING')
        audio = None
        try:
            actor = require('assistant.use')  # resolved here: the worker thread has no session
            audio = await run.io_bound(capture.stop)
            # El vocabulario del puesto y una búsqueda más amplia: la frase es corta y se dicta
            # una sola vez, así que conviene gastar el tiempo extra en acertarla.
            said, _ = await run.io_bound(transcribe_audio, audio, TRANSCRIPTION_PROMPT, 5)
            await run_command(said, actor)
        except Exception as exc:
            render('ERROR', result=str(exc))
            ui.timer(5, reset, once=True)
        finally:
            audio = None  # the command audio is never stored nor reused
            capture.chunks.clear()

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
