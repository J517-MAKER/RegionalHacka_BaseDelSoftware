"""Live facial recognition: the webcam of this computer against the people being searched."""
import time
from fastapi import Response
from nicegui import app, run, ui
import config
from components.case_form import NewCaseDialog
from components.layout import PageLayout, Panel, guard_page
from components.states import EmptyState
from components.status_badge import StatusBadge
from services.cameras_service import get_cameras
from services.cases_service import get_active_cases
from services.live_recognition_service import LiveRecognitionError, live
from services.users_service import can, require

LEGEND = [('#4caf50', 'ALTA'), ('#ffc800', 'MEDIA'), ('#ff8c00', 'BAJA'), ('#aaaaaa', 'Sin coincidencia')]
DEVICES = {0: 'Webcam 1 (predeterminada)', 1: 'Webcam 2', 2: 'Webcam 3'}


@app.get('/live/frame.jpg')
def live_frame():
    """Newest annotated frame. Only exists while recognition runs; nothing is stored."""
    content = live.frame_jpeg()
    if content is None:
        return Response(status_code=404)
    return Response(content=content, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})


def clean(name):
    return (name or '').replace(' (ficticia)', '').replace(' (ficticio)', '')


@ui.page('/live')
def live_page():
    if not guard_page('/live', 'live.view'):
        return
    with PageLayout('/live', 'Reconocimiento facial en vivo',
                    'La cámara de este equipo compara cada rostro con las personas en búsqueda. '
                    'Toda coincidencia requiere revisión humana.'):
        state = {'busy': False, 'error': None, 'gallery': None,
                 'seen': {item['detection'].id for item in live.detections}}

        @ui.refreshable
        def gallery():
            cases, counts = get_active_cases(), live.gallery_counts()
            if not cases:
                EmptyState('No hay casos en búsqueda.')
            for case in cases:
                with ui.link(target=f'/cases/{case.id}').classes('case-row no-underline text-inherit'):
                    ui.image(case.person.photos[0] if case.person.photos else '/assets/demo/person-1.svg') \
                        .classes('case-thumb')
                    with ui.column().classes('gap-0 min-w-0'):
                        ui.label(clean(case.person.name)).classes('text-xs font-medium')
                        ui.label(case.id).classes('mono muted')
                    ui.space()
                    if live.running:
                        usable = counts.get(case.id, 0)
                        ui.label(f'{usable} foto(s) útil(es)' if usable else 'Sin foto útil') \
                            .classes('text-[10px] ' + ('' if usable else 'muted'))
                    else:
                        ui.label(f'{len(case.person.photos)} foto(s)').classes('text-[10px] muted')

        @ui.refreshable
        def detections():
            if not live.detections:
                EmptyState('Sin detecciones todavía.')
                return
            for item in live.detections[:8]:
                detection, match = item['detection'], item['match']
                with ui.row().classes('items-center gap-3 w-full border-b border-[#edf0f2] py-2 no-wrap'):
                    ui.image(detection.capture).classes('w-12 h-14 shrink-0').props('fit=cover')
                    with ui.column().classes('gap-1 flex-1 min-w-0'):
                        ui.label(f'{detection.case_id} · {clean(item["name"])}').classes('text-xs font-medium')
                        ui.label(f'{detection.timestamp[11:]} · {detection.camera_id} · similitud '
                                 f'{detection.similarity} %').classes('text-[10px] muted')
                        StatusBadge(match.status)
                    ui.button('Revisar', on_click=lambda d=detection, m=match:
                              ui.navigate.to(f'/matches?case_id={d.case_id}&match_id={m.id}')) \
                        .props('flat dense no-caps')

        async def start():
            if state['busy']:
                return
            state['busy'] = True
            refresh()
            try:
                actor = require('live.control')
                await run.io_bound(live.start, camera.value, device.value, actor)
                ui.notify('Reconocimiento iniciado. Los cuadros no se guardan.', type='positive',
                          position='bottom-right')
            except (LiveRecognitionError, PermissionError) as error:
                ui.notify(str(error), type='warning', position='bottom-right')
            finally:
                state['busy'] = False
                refresh()

        async def stop():
            if state['busy']:
                return
            state['busy'] = True
            try:
                actor = require('live.control')
                await run.io_bound(live.stop, actor)
                ui.notify('Reconocimiento detenido. La cámara quedó libre.', type='info', position='bottom-right')
            except PermissionError as error:
                ui.notify(str(error), type='warning', position='bottom-right')
            finally:
                state['busy'] = False
                refresh()

        def register():
            try:
                require('cases.manage')
                photo = live.capture_face_photo()
            except (LiveRecognitionError, PermissionError) as error:
                ui.notify(str(error), type='warning', position='bottom-right')
                return
            NewCaseDialog(on_created=gallery.refresh, photos=[photo], navigate=False)

        with ui.element('div').classes('workspace-grid'):
            with ui.column().classes('w-full gap-5 min-w-0'):
                with Panel('01 / Cámara del equipo', 'LOCAL · LOS CUADROS NO SE GUARDAN'):
                    # Compact video on the left, controls beside it; they stack on narrow screens.
                    with ui.row().classes('p-4 w-full gap-5 items-start live-layout'):
                        with ui.column().classes('live-screen gap-2'):
                            video = ui.interactive_image().classes('w-full live-video')
                            with ui.column().classes('w-full items-center justify-center gap-2 live-idle') as idle:
                                ui.icon('videocam_off', size='30px', color='blue-grey-4')
                                ui.label('Cámara detenida').classes('text-sm muted')
                            hint = ui.label('Imagen negra: la cámara funciona pero no recibe luz. Destapa el lente '
                                            'o ilumina la escena.').classes('notice')
                        with ui.column().classes('live-controls gap-3'):
                            with ui.row().classes('items-center gap-2'):
                                dot = ui.element('span').classes('status-dot')
                                status = ui.label('DETENIDA').classes('text-lg font-medium')
                            info = ui.label('').classes('text-xs muted')
                            camera = ui.select({c.id: f'{c.id} — {c.name}' for c in get_cameras()
                                                if c.status != 'Desconectada'},
                                               value=live.camera_id, label='Cámara de la red asociada') \
                                .props('outlined dense').classes('w-full')
                            device = ui.select(DEVICES, value=live.camera_index if live.camera_index in DEVICES else 0,
                                               label='Dispositivo').props('outlined dense').classes('w-full')
                            start_button = ui.button('INICIAR RECONOCIMIENTO', icon='videocam', on_click=start) \
                                .props('unelevated no-caps').classes('w-full').mark('live-start')
                            stop_button = ui.button('DETENER', icon='stop', on_click=stop) \
                                .props('outline no-caps').classes('w-full').mark('live-stop')
                            register_button = ui.button('Registrar persona con esta cámara', icon='person_add',
                                                        on_click=register).props('outline no-caps') \
                                .classes('w-full').mark('live-register')
                            with ui.row().classes('items-center gap-3 flex-wrap'):
                                for color, label in LEGEND:
                                    with ui.row().classes('items-center gap-1'):
                                        ui.element('span').style(f'width:10px;height:10px;border-radius:2px;'
                                                                 f'background:{color};display:inline-block')
                                        ui.label(label).classes('text-[11px]')
                            ui.label('Los cuadros sólo existen en memoria. Se conserva únicamente el recorte del '
                                     'rostro de una posible coincidencia, para que un operador la valide o la '
                                     'descarte.').classes('text-xs muted')
            with ui.element('div').classes('stack'):
                with Panel('Personas en búsqueda', 'SE COMPARAN EN VIVO'):
                    with ui.column().classes('w-full gap-0'):
                        gallery()
                    with ui.column().classes('p-4 gap-2 w-full'):
                        ui.button('Registrar persona con fotografía', icon='upload',
                                  on_click=lambda: NewCaseDialog(on_created=gallery.refresh, navigate=False)) \
                            .props('outline no-caps').set_enabled(can('cases.manage'))
                        ui.label('Sólo cuentan fotografías reales con un rostro visible; las ilustraciones de '
                                 'demostración no se comparan.').classes('text-[10px] muted')
                with Panel('Detecciones recientes', 'PENDIENTES DE VALIDACIÓN'):
                    with ui.column().classes('px-4 py-2 w-full gap-0'):
                        detections()
                    ui.link('Revisar todas las coincidencias →', '/matches') \
                        .classes('text-[11px] no-underline px-4 py-3 block border-t border-[#edf0f2]')

        def refresh():
            running = live.running
            status.set_text('INICIANDO…' if state['busy'] and not running else live.status)
            dot.classes(replace='status-dot ' + ('green' if running else ''))
            info.set_text(f'{live.fps:.1f} análisis/s · {len(live.faces)} rostro(s) en cuadro · '
                          f'{len(live.gallery_counts())} persona(s) comparables' if running else '')
            video.set_visibility(running)
            idle.set_visibility(not running)
            hint.set_visibility(running and live.dark)
            start_button.set_enabled(not running and not state['busy'] and can('live.control'))
            stop_button.set_enabled(running and not state['busy'] and can('live.control'))
            register_button.set_enabled(running and can('cases.manage'))
            camera.set_enabled(not running)
            device.set_enabled(not running)
            if live.error and live.error != state['error']:
                ui.notify(live.error, type='warning', position='bottom-right')
            state['error'] = live.error
            new = [item for item in live.detections if item['detection'].id not in state['seen']]
            for item in new:
                state['seen'].add(item['detection'].id)
                ui.notify(f'Posible coincidencia: {item["detection"].case_id} · {clean(item["name"])} '
                          f'({item["detection"].similarity} %)', type='warning', position='top-right', timeout=6000)
            if new:
                detections.refresh()
            key = (running, tuple(sorted(live.gallery_counts().items())), tuple(c.id for c in get_active_cases()))
            if key != state['gallery']:
                state['gallery'] = key
                gallery.refresh()

        def next_frame():
            if live.running:
                video.set_source(f'/live/frame.jpg?{time.time()}')

        refresh()
        ui.timer(.5, refresh)
        ui.timer(.1, next_frame)
