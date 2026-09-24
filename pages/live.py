"""Live facial recognition: webcams of this computer against the people being searched."""
import time
from fastapi import Response
from nicegui import app, run, ui
import config
from components.case_form import NewCaseDialog
from components.layout import PageLayout, Panel, guard_page
from components.states import EmptyState
from components.status_badge import StatusBadge
from services.camera_monitor_service import monitor
from services.cameras_service import get_cameras
from services.cases_service import get_active_cases
from services import live_recognition_service as live_service
from services.live_recognition_service import (
    KIND_LABELS, LIVE_INSTANCES, LiveRecognitionError, find_device, get_live_for_camera, live_1, live_2, live_3
)
from services.users_service import can, require

LEGEND = [('#4caf50', 'ALTA'), ('#ffc800', 'MEDIA'), ('#ff8c00', 'BAJA'), ('#aaaaaa', 'Sin coincidencia')]
SLOTS = {'1': live_1, '2': live_2, '3': live_3}
TITLES = {'1': '01 / Cámara 1 · Laptop', '2': '02 / Cámara 2 · Webcam USB', '3': '03 / Cámara 3 · Celular'}
IDLE_HINTS = {'3': 'Enlaza el celular con Enlace Móvil de Windows y pulsa INICIAR'}


def device_options(inst, devices):
    """'auto' finds this slot's physical camera by name; the rest pin a device by index."""
    found = find_device(inst.kind, devices=devices)
    auto = f'Automático · {found["name"]}' if found else f'Automático · {KIND_LABELS[inst.kind].lower()} no detectada'
    options = {'auto': auto}
    for device in devices:
        options[device['index']] = f'{device["index"]} · {device["name"]} ({KIND_LABELS[device["kind"]]})'
    return options


def frame_response(inst):
    content = inst.frame_jpeg() if inst else None
    if content is None:
        return Response(status_code=404)
    return Response(content=content, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})


@app.get('/live/slot/{slot}.jpg')
def live_slot_frame(slot: str):
    """Newest frame of one physical camera slot: each panel reads only its own device."""
    return frame_response(SLOTS.get(slot))


@app.get('/live/frame.jpg')
@app.get('/live/frame/{camera_id}.jpg')
def live_frame(camera_id: str = None):
    """Newest frame of the network camera; 404 when no slot runs on it (never another camera's)."""
    return frame_response(get_live_for_camera(camera_id) if camera_id else live_1)


def clean(name):
    return (name or '').replace(' (ficticia)', '').replace(' (ficticio)', '')


@ui.page('/live')
def live_page():
    if not guard_page('/live', 'live.view'):
        return
    with PageLayout('/live', 'Reconocimiento facial en vivo',
                    'La cámara de la laptop, la webcam USB y el celular enlazado, contra las personas en búsqueda.'):

        state = {'busy': {n: False for n in SLOTS}, 'seen': set(), 'gallery': None,
                 'devices': live_service.list_video_devices()}
        panels = {}  # slot -> widgets of its panel

        def all_detections():
            items = [item for inst in LIVE_INSTANCES for item in inst.detections]
            return sorted(items, key=lambda x: x['detection'].timestamp, reverse=True)

        @ui.refreshable
        def gallery():
            cases = get_active_cases()
            counts = {}
            for inst in LIVE_INSTANCES:
                if inst.running:
                    counts.update(inst.gallery_counts())
            live_now = any(inst.running for inst in LIVE_INSTANCES)
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
                    if live_now:
                        usable = counts.get(case.id, 0)
                        ui.label(f'{usable} foto(s) útil(es)' if usable else 'Sin foto útil') \
                            .classes('text-[10px] ' + ('' if usable else 'muted'))
                    else:
                        ui.label(f'{len(case.person.photos)} foto(s)').classes('text-[10px] muted')

        @ui.refreshable
        def detections():
            items = all_detections()
            if not items:
                EmptyState('Sin detecciones todavía.')
                return
            for item in items[:10]:
                detection, match = item['detection'], item['match']
                with ui.row().classes('items-center gap-3 w-full border-b border-[#edf0f2] py-2 no-wrap'):
                    ui.image(detection.capture).classes('w-12 h-14 shrink-0').props('fit=cover')
                    with ui.column().classes('gap-1 flex-1 min-w-0'):
                        ui.label(f'{detection.case_id} · {clean(item["name"])}').classes('text-xs font-medium')
                        ui.label(f'{detection.timestamp[11:]} · {detection.camera_id} · '
                                 f'{item["level"]}').classes('text-[10px] muted')
                        StatusBadge(match.status)
                    ui.button('Revisar', on_click=lambda d=detection, m=match:
                              ui.navigate.to(f'/matches?case_id={d.case_id}&match_id={m.id}')) \
                        .props('flat dense no-caps')

        async def start_cam(slot):
            inst, widgets = SLOTS[slot], panels[slot]
            if state['busy'][slot] or inst.running:
                return
            state['busy'][slot] = True
            refresh()
            try:
                actor = require('live.control')
                device = None if widgets['dev'].value == 'auto' else widgets['dev'].value
                await run.io_bound(inst.start, widgets['cam'].value, device, actor)
                inst.paused_by = ''
                monitor.paused_by = ''  # un arranque manual deshace una pausa previa del monitoreo continuo
                ui.notify(f'{inst.name} iniciada: {inst.device_name or "dispositivo " + str(inst.camera_index)} '
                          f'→ {inst.camera_id}.', type='positive', position='bottom-right')
            except (LiveRecognitionError, PermissionError) as error:
                ui.notify(str(error), type='warning', position='bottom-right', multi_line=True)
            finally:
                state['busy'][slot] = False
                refresh()

        async def stop_cam(slot):
            inst = SLOTS[slot]
            if state['busy'][slot] or not inst.running:
                return
            state['busy'][slot] = True
            try:
                actor = require('live.control')
                inst.paused_by = actor  # el monitoreo continuo no la vuelve a abrir sola
                await run.io_bound(inst.stop, actor)
                ui.notify(f'{inst.name} pausada ({inst.camera_id}). Queda libre hasta que la inicies.',
                          type='info', position='bottom-right')
            except PermissionError as error:
                ui.notify(str(error), type='warning', position='bottom-right')
            finally:
                state['busy'][slot] = False
                refresh()

        async def detect_devices():
            state['devices'] = await run.io_bound(live_service.list_video_devices)
            indexes = [d['index'] for d in state['devices']]
            for slot, widgets in panels.items():
                select = widgets['dev']
                select.set_options(device_options(SLOTS[slot], state['devices']),
                                   value=select.value if select.value in indexes else 'auto')
            detected.refresh()
            ui.notify(f'{len(state["devices"])} dispositivo(s) de video detectado(s).', position='bottom-right')

        @ui.refreshable
        def detected():
            usable = [d for d in state['devices'] if d['kind'] != 'virtual']
            if not usable:
                ui.label('No se detectaron cámaras.').classes('text-[11px] muted')
            for d in usable:
                ui.label(f'● {KIND_LABELS[d["kind"]]}: {d["name"]} (dispositivo {d["index"]})').classes('text-[11px]')

        async def start_all():
            for slot in SLOTS:
                await start_cam(slot)

        async def stop_all_cams():
            for slot in SLOTS:
                await stop_cam(slot)

        def register_from(inst):
            try:
                require('cases.manage')
                photo = inst.capture_face_photo()
            except (LiveRecognitionError, PermissionError) as error:
                ui.notify(str(error), type='warning', position='bottom-right')
                return
            NewCaseDialog(on_created=gallery.refresh, photos=[photo], navigate=False)

        def camera_panel(slot):
            """Video, estado y controles de una cámara física; la primera lleva las marcas de los tests."""
            inst, first = SLOTS[slot], slot == '1'
            networks = {c.id: f'{c.id} — {c.name}' for c in get_cameras() if c.status != 'Desconectada'}
            with Panel(TITLES[slot], f'RED: {inst.camera_id}'):
                with ui.column().classes('p-3 w-full gap-3'):
                    with ui.element('div').classes('relative w-full aspect-video bg-[#0f172a] rounded-lg overflow-hidden '
                                                   'flex items-center justify-center'):
                        video = ui.interactive_image().classes('w-full h-full object-cover')
                        with ui.column().classes('items-center justify-center gap-1 px-4 text-center') as idle:
                            ui.icon('smartphone' if inst.kind == 'phone' else 'videocam_off', size='28px',
                                    color='blue-grey-4')
                            ui.label(f'Cámara {slot} detenida').classes('text-xs text-gray-400')
                            if slot in IDLE_HINTS:
                                ui.label(IDLE_HINTS[slot]).classes('text-[10px] text-gray-500')
                    with ui.row().classes('items-center justify-between w-full'):
                        with ui.row().classes('items-center gap-2'):
                            dot = ui.element('span').classes('status-dot')
                            status = ui.label('DETENIDA').classes('text-sm font-semibold')
                        info = ui.label('').classes('text-[11px] text-gray-500')
                    device = ui.label('').classes('text-[11px] text-gray-500')
                    cam = ui.select(networks, value=inst.camera_id if inst.camera_id in networks else None,
                                    label='Cámara de red').props('outlined dense').classes('w-full')
                    dev = ui.select(device_options(inst, state['devices']), value='auto',
                                    label='Dispositivo físico').props('outlined dense').classes('w-full')
                    with ui.row().classes('w-full gap-2'):
                        start_btn = ui.button('INICIAR', icon='videocam', on_click=lambda: start_cam(slot)) \
                            .props('unelevated no-caps').classes('flex-1')
                        stop_btn = ui.button('DETENER', icon='stop', on_click=lambda: stop_cam(slot)) \
                            .props('outline no-caps').classes('flex-1')
                    register = ui.button('Registrar persona con esta cámara', icon='person_add',
                                         on_click=lambda: register_from(inst)) \
                        .props('flat dense no-caps').classes('w-full text-xs')
                    if first:
                        start_btn.mark('live-start')
                        stop_btn.mark('live-stop')
                        register.mark('live-register')
            panels[slot] = {'video': video, 'idle': idle, 'dot': dot, 'status': status, 'info': info,
                            'device': device, 'cam': cam, 'dev': dev, 'start': start_btn, 'stop': stop_btn}

        with ui.element('div').classes('workspace-grid'):
            with ui.column().classes('w-full gap-5 min-w-0'):
                with ui.row().classes('items-center justify-between w-full bg-white p-3 rounded-xl border border-[#e2e8f0]'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('videocam', color='primary', size='22px')
                        ui.label('Monitoreo facial simultáneo · laptop, USB y celular').classes('font-semibold text-sm')
                    with ui.row().classes('gap-2'):
                        ui.button('INICIAR TODAS', icon='play_arrow', on_click=start_all) \
                            .props('unelevated no-caps size=sm color=primary')
                        ui.button('DETENER TODAS', icon='stop', on_click=stop_all_cams) \
                            .props('outline no-caps size=sm')
                        ui.button('Detectar cámaras', icon='search', on_click=detect_devices) \
                            .props('flat no-caps size=sm').mark('live-detect')
                with ui.column().classes('w-full gap-0 px-1'):
                    detected()

                with ui.element('div').style('display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); '
                                             'gap:16px; width:100%;'):
                    for slot in SLOTS:
                        camera_panel(slot)

                with ui.row().classes('items-center gap-3 px-4 py-2 bg-white rounded-lg border border-[#e2e8f0]'):
                    ui.label('Nivel de coincidencia:').classes('text-xs font-medium text-gray-600')
                    for color, label in LEGEND:
                        with ui.row().classes('items-center gap-1'):
                            ui.element('span').style(f'width:10px;height:10px;border-radius:2px;background:{color};display:inline-block')
                            ui.label(label).classes('text-[11px]')

            with ui.element('div').classes('stack'):
                with Panel('Personas en búsqueda', 'SE COMPARAN EN VIVO'):
                    with ui.column().classes('w-full gap-0'):
                        gallery()
                    with ui.column().classes('p-4 gap-2 w-full'):
                        ui.button('Registrar persona con fotografía', icon='upload',
                                  on_click=lambda: NewCaseDialog(on_created=gallery.refresh, navigate=False)) \
                            .props('outline no-caps').set_enabled(can('cases.manage'))
                        ui.label('Sólo cuentan fotografías reales con un rostro visible.').classes('text-[10px] muted')
                with Panel('Detecciones recientes', 'PENDIENTES DE VALIDACIÓN'):
                    with ui.column().classes('px-4 py-2 w-full gap-0'):
                        detections()
                    ui.link('Revisar todas las coincidencias →', '/matches') \
                        .classes('text-[11px] no-underline px-4 py-3 block border-t border-[#edf0f2]')

        def refresh():
            allowed = can('live.control')
            for slot, w in panels.items():
                inst, busy = SLOTS[slot], state['busy'][slot]
                running = inst.running
                # Windows muestra un cuadro negro con un círculo mientras el celular no acepta la conexión.
                waiting = running and inst.kind == 'phone' and inst.dark
                w['status'].set_text('INICIANDO…' if busy and not running else
                                     'ESPERANDO AL CELULAR' if waiting else
                                     'PAUSADA' if not running and (inst.paused_by or monitor.paused_by) else inst.status)
                w['dot'].classes(replace='status-dot ' + ('green' if running and not waiting else ''))
                w['info'].set_text('Desbloquea el celular y acepta la conexión' if waiting else
                                   f'{inst.fps:.1f} fps · {len(inst.faces)} rostro(s)' if running else '')
                w['device'].set_text(f'Dispositivo {inst.camera_index} · {inst.device_name or "sin nombre"} '
                                     f'→ {inst.camera_id}' if running else '')
                w['video'].set_visibility(running)
                w['idle'].set_visibility(not running)
                w['start'].set_enabled(not running and not busy and allowed)
                w['stop'].set_enabled(running and not busy and allowed)
                w['cam'].set_enabled(not running)
                w['dev'].set_enabled(not running)

            new = [item for item in all_detections() if item['detection'].id not in state['seen']]
            for item in new:
                state['seen'].add(item['detection'].id)
                ui.notify(f'Posible coincidencia: {item["detection"].case_id} · {clean(item["name"])} '
                          f'({item["level"]}) en {item["detection"].camera_id}',
                          type='warning', position='top-right', timeout=6000)
            if new:
                detections.refresh()

            key = (tuple(inst.running for inst in LIVE_INSTANCES), len(get_active_cases()))
            if key != state['gallery']:
                state['gallery'] = key
                gallery.refresh()

        def next_frame():
            for slot, w in panels.items():
                if SLOTS[slot].running:
                    w['video'].set_source(f'/live/slot/{slot}.jpg?{time.time()}')

        refresh()
        ui.timer(.5, refresh)
        ui.timer(.1, next_frame)
