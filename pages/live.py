"""Live facial recognition: webcams of this computer against the people being searched."""
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
from services.live_recognition_service import (
    LiveRecognitionError, live, live_1, live_2, LIVE_INSTANCES,
    get_live_for_camera, is_live_camera
)
from services.users_service import can, require

LEGEND = [('#4caf50', 'ALTA'), ('#ffc800', 'MEDIA'), ('#ff8c00', 'BAJA'), ('#aaaaaa', 'Sin coincidencia')]
DEVICES = {
    0: 'Dispositivo 0 · Cámara de laptop / integrada',
    1: 'Dispositivo 1 · Webcam USB externa',
    2: 'Dispositivo 2 · Otra fuente de video'
}


@app.get('/live/frame.jpg')
@app.get('/live/frame/{camera_id}.jpg')
@app.get('/live/frame/{camera_id}')
def live_frame(camera_id: str = None):
    """Newest annotated frame for requested camera."""
    inst = get_live_for_camera(camera_id) if camera_id else live_1
    if not inst:
        inst = live_1
    content = inst.frame_jpeg()
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
                    'Uso simultáneo de la cámara de la laptop y la webcam USB externa contra las personas en búsqueda.'):
        
        state = {'busy_1': False, 'busy_2': False, 'seen': set(), 'gallery': None}

        @ui.refreshable
        def gallery():
            cases = get_active_cases()
            counts_1 = live_1.gallery_counts() if live_1.running else {}
            counts_2 = live_2.gallery_counts() if live_2.running else {}
            counts = {**counts_1, **counts_2}
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
                    if live_1.running or live_2.running:
                        usable = counts.get(case.id, 0)
                        ui.label(f'{usable} foto(s) útil(es)' if usable else 'Sin foto útil') \
                            .classes('text-[10px] ' + ('' if usable else 'muted'))
                    else:
                        ui.label(f'{len(case.person.photos)} foto(s)').classes('text-[10px] muted')

        @ui.refreshable
        def detections():
            all_dets = list(live_1.detections) + list(live_2.detections)
            all_dets.sort(key=lambda x: x['detection'].timestamp, reverse=True)
            if not all_dets:
                EmptyState('Sin detecciones todavía.')
                return
            for item in all_dets[:10]:
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

        async def start_cam(inst, cam_select, dev_select, busy_key):
            if state[busy_key]:
                return
            state[busy_key] = True
            refresh()
            try:
                actor = require('live.control')
                await run.io_bound(inst.start, cam_select.value, dev_select.value, actor)
                ui.notify(f'{inst.name} iniciada ({cam_select.value} · Disp. {dev_select.value}).',
                          type='positive', position='bottom-right')
            except (LiveRecognitionError, PermissionError) as error:
                ui.notify(str(error), type='warning', position='bottom-right')
            finally:
                state[busy_key] = False
                refresh()

        async def stop_cam(inst, busy_key):
            if state[busy_key]:
                return
            state[busy_key] = True
            try:
                actor = require('live.control')
                await run.io_bound(inst.stop, actor)
                ui.notify(f'{inst.name} detenida ({inst.camera_id}).', type='info', position='bottom-right')
            except PermissionError as error:
                ui.notify(str(error), type='warning', position='bottom-right')
            finally:
                state[busy_key] = False
                refresh()

        async def start_all():
            await start_cam(live_1, cam_1, dev_1, 'busy_1')
            await start_cam(live_2, cam_2, dev_2, 'busy_2')

        async def stop_all_cams():
            await stop_cam(live_1, 'busy_1')
            await stop_cam(live_2, 'busy_2')

        def register_from(inst):
            try:
                require('cases.manage')
                photo = inst.capture_face_photo()
            except (LiveRecognitionError, PermissionError) as error:
                ui.notify(str(error), type='warning', position='bottom-right')
                return
            NewCaseDialog(on_created=gallery.refresh, photos=[photo], navigate=False)

        with ui.element('div').classes('workspace-grid'):
            with ui.column().classes('w-full gap-5 min-w-0'):
                # Global Action Bar
                with ui.row().classes('items-center justify-between w-full bg-white p-3 rounded-xl border border-[#e2e8f0]'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('videocam', color='primary', size='22px')
                        ui.label('Monitoreo facial dual simultáneo').classes('font-semibold text-sm')
                    with ui.row().classes('gap-2'):
                        ui.button('INICIAR AMBAS', icon='play_arrow', on_click=start_all) \
                            .props('unelevated no-caps size=sm color=primary')
                        ui.button('DETENER AMBAS', icon='stop', on_click=stop_all_cams) \
                            .props('outline no-caps size=sm')

                # Dual Camera Columns
                with ui.element('div').style('display:grid; grid-template-columns:repeat(auto-fit, minmax(320px, 1fr)); gap:16px; width:100%;'):
                    
                    # ── Panel Cámara 1 (Laptop) ──
                    with Panel('01 / Cámara 1 · Laptop', f'RED: {live_1.camera_id}'):
                        with ui.column().classes('p-3 w-full gap-3'):
                            with ui.element('div').classes('relative w-full aspect-video bg-[#0f172a] rounded-lg overflow-hidden flex items-center justify-center'):
                                video_1 = ui.interactive_image().classes('w-full h-full object-cover')
                                with ui.column().classes('items-center justify-center gap-1') as idle_1:
                                    ui.icon('videocam_off', size='28px', color='blue-grey-4')
                                    ui.label('Cámara 1 detenida').classes('text-xs text-gray-400')
                            with ui.row().classes('items-center justify-between w-full'):
                                with ui.row().classes('items-center gap-2'):
                                    dot_1 = ui.element('span').classes('status-dot')
                                    status_1 = ui.label('DETENIDA').classes('text-sm font-semibold')
                                info_1 = ui.label('').classes('text-[11px] text-gray-500')
                            cam_1 = ui.select({c.id: f'{c.id} — {c.name}' for c in get_cameras() if c.status != 'Desconectada'},
                                              value=live_1.camera_id, label='Cámara de red').props('outlined dense').classes('w-full')
                            dev_1 = ui.select(DEVICES, value=live_1.camera_index if live_1.camera_index in DEVICES else 0,
                                              label='Hardware').props('outlined dense').classes('w-full')
                            with ui.row().classes('w-full gap-2'):
                                start_btn_1 = ui.button('INICIAR', icon='videocam', on_click=lambda: start_cam(live_1, cam_1, dev_1, 'busy_1')) \
                                    .props('unelevated no-caps').classes('flex-1')
                                stop_btn_1 = ui.button('DETENER', icon='stop', on_click=lambda: stop_cam(live_1, 'busy_1')) \
                                    .props('outline no-caps').classes('flex-1')
                            ui.button('Registrar persona con esta cámara', icon='person_add', on_click=lambda: register_from(live_1)) \
                                .props('flat dense no-caps').classes('w-full text-xs')

                    # ── Panel Cámara 2 (Webcam USB) ──
                    with Panel('02 / Cámara 2 · Webcam USB', f'RED: {live_2.camera_id}'):
                        with ui.column().classes('p-3 w-full gap-3'):
                            with ui.element('div').classes('relative w-full aspect-video bg-[#0f172a] rounded-lg overflow-hidden flex items-center justify-center'):
                                video_2 = ui.interactive_image().classes('w-full h-full object-cover')
                                with ui.column().classes('items-center justify-center gap-1') as idle_2:
                                    ui.icon('videocam_off', size='28px', color='blue-grey-4')
                                    ui.label('Cámara 2 detenida').classes('text-xs text-gray-400')
                            with ui.row().classes('items-center justify-between w-full'):
                                with ui.row().classes('items-center gap-2'):
                                    dot_2 = ui.element('span').classes('status-dot')
                                    status_2 = ui.label('DETENIDA').classes('text-sm font-semibold')
                                info_2 = ui.label('').classes('text-[11px] text-gray-500')
                            cam_2 = ui.select({c.id: f'{c.id} — {c.name}' for c in get_cameras() if c.status != 'Desconectada'},
                                              value=live_2.camera_id, label='Cámara de red').props('outlined dense').classes('w-full')
                            dev_2 = ui.select(DEVICES, value=live_2.camera_index if live_2.camera_index in DEVICES else 1,
                                              label='Hardware').props('outlined dense').classes('w-full')
                            with ui.row().classes('w-full gap-2'):
                                start_btn_2 = ui.button('INICIAR', icon='videocam', on_click=lambda: start_cam(live_2, cam_2, dev_2, 'busy_2')) \
                                    .props('unelevated no-caps').classes('flex-1')
                                stop_btn_2 = ui.button('DETENER', icon='stop', on_click=lambda: stop_cam(live_2, 'busy_2')) \
                                    .props('outline no-caps').classes('flex-1')
                            ui.button('Registrar persona con esta cámara', icon='person_add', on_click=lambda: register_from(live_2)) \
                                .props('flat dense no-caps').classes('w-full text-xs')

                # Legend
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
            # Refresh Cam 1
            run_1 = live_1.running
            status_1.set_text('INICIANDO…' if state['busy_1'] and not run_1 else live_1.status)
            dot_1.classes(replace='status-dot ' + ('green' if run_1 else ''))
            info_1.set_text(f'{live_1.fps:.1f} fps · {len(live_1.faces)} rostro(s)' if run_1 else '')
            video_1.set_visibility(run_1)
            idle_1.set_visibility(not run_1)
            start_btn_1.set_enabled(not run_1 and not state['busy_1'] and can('live.control'))
            stop_btn_1.set_enabled(run_1 and not state['busy_1'] and can('live.control'))
            cam_1.set_enabled(not run_1)
            dev_1.set_enabled(not run_1)

            # Refresh Cam 2
            run_2 = live_2.running
            status_2.set_text('INICIANDO…' if state['busy_2'] and not run_2 else live_2.status)
            dot_2.classes(replace='status-dot ' + ('green' if run_2 else ''))
            info_2.set_text(f'{live_2.fps:.1f} fps · {len(live_2.faces)} rostro(s)' if run_2 else '')
            video_2.set_visibility(run_2)
            idle_2.set_visibility(not run_2)
            start_btn_2.set_enabled(not run_2 and not state['busy_2'] and can('live.control'))
            stop_btn_2.set_enabled(run_2 and not state['busy_2'] and can('live.control'))
            cam_2.set_enabled(not run_2)
            dev_2.set_enabled(not run_2)

            # Notifications on new detections from any camera
            all_dets = list(live_1.detections) + list(live_2.detections)
            new = [item for item in all_dets if item['detection'].id not in state['seen']]
            for item in new:
                state['seen'].add(item['detection'].id)
                ui.notify(f'Coincidencia [{item["detection"].camera_id}]: {item["detection"].case_id} · {clean(item["name"])} '
                          f'({item["detection"].similarity} %)', type='warning', position='top-right', timeout=6000)
            if new:
                detections.refresh()

            key = (run_1, run_2, len(get_active_cases()))
            if key != state['gallery']:
                state['gallery'] = key
                gallery.refresh()

        def next_frame():
            if live_1.running:
                video_1.set_source(f'/live/frame/{live_1.camera_id}.jpg?{time.time()}')
            if live_2.running:
                video_2.set_source(f'/live/frame/{live_2.camera_id}.jpg?{time.time()}')

        refresh()
        ui.timer(.5, refresh)
        ui.timer(.1, next_frame)
