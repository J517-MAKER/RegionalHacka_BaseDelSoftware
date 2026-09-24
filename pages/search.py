"""Búsqueda por ficha: ¿esta persona ya está en la base de datos de NEXO?

Se parte de una ficha registrada, de una ficha nueva (imagen o PDF, se lee con OCR) o de una
fotografía autorizada. Sus rasgos se comparan con todo lo que las cámaras guardaron —personas
vistas en eventos de auxilio, detecciones y la base compartida— y con las demás fichas
(posibles duplicados). Cada resultado se muestra lado a lado: la ficha y la persona de la
cámara, cuánto se parecen, sus características y el contexto de fecha y lugar.
"""
from nicegui import run, ui
import config
from components.face_comparison import FaceComparison, LevelBadge, capture_side, ficha_side
from components.layout import PageLayout, Panel, guard_page, notify_action
from components.person_profile import InfoPair
from components.states import EmptyState
from services import face_search_service as searcher
from services.cases_service import get_case, get_cases
from services.search_matching_service import ensure_profile, profile_from_reference, promote_result
from services.users_service import can, require

SOURCE_LABELS = {'EVENTO': 'Evento de auxilio', 'DETECCION': 'Detección de cámara', 'CAPTURA_BD': 'Base compartida'}


def clean(name):
    return (name or '').replace(' (ficticia)', '').replace(' (ficticio)', '')


@ui.page('/search')
def search_page(case_id: str = ''):
    if not guard_page('/search', 'cases.import', 'matches.supervise'):
        return
    with PageLayout('/search', 'Búsqueda por ficha',
                    'Comprueba si una persona de una ficha de búsqueda ya aparece en lo que registraron las '
                    'cámaras. Los resultados son pistas para revisión humana, nunca una identificación.'):
        state = {'profile': None, 'case': None, 'reference': None, 'results': [], 'fichas': [],
                 'summary': None, 'busy': False, 'fields': {}}

        # ── 01 · Referencia ─────────────────────────────────────────────────────────────
        with Panel('01 / Referencia', 'FICHA REGISTRADA, FICHA NUEVA O FOTOGRAFÍA AUTORIZADA'):
            with ui.column().classes('p-4 w-full gap-3'):
                engine_ready, engine_message = searcher.model_status()
                with ui.row().classes('items-center gap-3 w-full') as engine_row:
                    engine_icon = ui.icon('check_circle' if engine_ready else 'warning',
                                          color='positive' if engine_ready else 'warning')
                    engine_label = ui.label(engine_message).classes('text-xs')
                    download = ui.button('Descargar modelo facial', icon='download', on_click=lambda: get_model()) \
                        .props('outline dense no-caps').classes('ml-auto')
                    download.set_visibility(not engine_ready and can('cases.import'))

                def watch_engine():
                    """El modelo se prepara solo al arrancar NEXO: la página se habilita sola al terminar."""
                    ready, message = searcher.model_status()
                    engine_label.set_text(message)
                    if ready:
                        engine_icon.set_name('check_circle')
                        engine_icon.props('color=positive')
                        download.set_visibility(False)
                        engine_watch.deactivate()
                engine_watch = ui.timer(3, watch_engine, active=not engine_ready)
                with ui.tabs().classes('w-full border-b border-[#dce2e7]') as tabs:
                    registered_tab = ui.tab('Ficha registrada', icon='folder_shared')
                    upload_tab = ui.tab('Subir ficha o fotografía autorizada', icon='upload_file')
                with ui.tab_panels(tabs, value=registered_tab).classes('w-full'):
                    with ui.tab_panel(registered_tab):
                        options = {c.id: f'{c.id} · {clean(c.person.name)}' for c in get_cases()}
                        case_select = ui.select(options, value=case_id if case_id in options else None,
                                                label='Ficha de búsqueda registrada', with_input=True) \
                            .props('outlined dense').classes('w-full max-w-xl')
                        ui.button('BUSCAR EN LA BASE DE DATOS', icon='travel_explore',
                                  on_click=lambda: search_registered()).props('unelevated no-caps') \
                            .mark('search-registered')
                    with ui.tab_panel(upload_tab):
                        kind = ui.radio({'photo': 'Fotografía autorizada (sólo el rostro)',
                                         'ficha': 'Ficha de búsqueda (imagen o PDF: se leen sus datos con OCR)'},
                                        value='photo').props('inline dense')
                        consent = ui.checkbox('Confirmo que la imagen proviene de una ficha oficial o de una fuente '
                                              'autorizada para la búsqueda de esta persona.')
                        uploader = ui.upload(label='Seleccionar imagen (JPG, PNG, WebP) o PDF de la ficha',
                                             on_upload=lambda e: upload(e), auto_upload=True, max_files=1,
                                             max_file_size=10 * 1024 * 1024,
                                             on_rejected=lambda: ui.notify('Archivo rechazado: máximo 10 MB.',
                                                                           type='warning')) \
                            .props('accept=.png,.jpg,.jpeg,.webp,.pdf flat bordered').classes('w-full')
                        uploader.set_enabled(can('cases.import'))
                        ui.label('Los datos de la referencia se usan sólo para esta consulta. La imagen se guarda '
                                 'temporalmente en imports/, fuera de la evidencia.').classes('text-[10px] muted')
                with ui.row().classes('items-center gap-3'):
                    spinner = ui.spinner(size='18px')
                    spinner.set_visibility(False)
                    status = ui.label('Elige una ficha registrada o sube una referencia.').classes('text-sm')

        # ── 02 · Rasgos de la referencia ────────────────────────────────────────────────
        @ui.refreshable
        def reference_panel():
            profile, reference = state['profile'], state['reference']
            if profile is None:
                return
            with Panel('02 / Rasgos de la referencia', 'LO QUE SE COMPARA'):
                with ui.element('div').classes('detail-grid p-4 w-full'):
                    with ui.column().classes('gap-2 items-start'):
                        photo = (reference or {}).get('crop') or profile.reference_photo
                        if photo:
                            ui.image(photo).classes('w-40 h-48 rounded').props('fit=cover')
                        if reference:
                            ui.label(f'Rostro detectado · {reference["faces"]} rostro(s) en la imagen'
                                     + (f' · edad aparente ~{reference["age"]} años' if reference.get('age') else '')) \
                                .classes('text-[11px] muted')
                        elif profile.face_embedding:
                            ui.label('Huella facial de la ficha registrada.').classes('text-[11px] muted')
                    with ui.column().classes('gap-2 w-full'):
                        if state['case'] is None:
                            ui.label('Datos declarados (corrígelos antes de buscar)').classes('section-title')
                            fields = {}
                            with ui.element('div').classes('field-grid'):
                                for key, label, value in [
                                        ('name', 'Nombre', profile.official_folio),
                                        ('age', 'Edad', profile.declared_age),
                                        ('missing_date', 'Fecha de desaparición', profile.disappearance_datetime[:10]),
                                        ('location', 'Último lugar conocido', profile.last_known_location),
                                        ('clothing', 'Vestimenta', profile.clothing_description),
                                        ('marks', 'Señas particulares', profile.distinctive_marks)]:
                                    fields[key] = ui.input(label, value=value or '').props('outlined dense')
                            state['fields'] = fields
                        else:
                            case = state['case']
                            InfoPair('Ficha', f'{case.id} · {clean(case.person.name)}')
                            InfoPair('Desaparición', f'{case.missing_date} · {case.missing_time}')
                            InfoPair('Último lugar conocido', case.location)
                            InfoPair('Vestimenta', case.person.clothing)
                        InfoPair('Referencia facial', 'Lista' if profile.face_embedding else profile.face_message
                                 or 'Sin huella facial')
                        if profile.last_known_lat is not None:
                            InfoPair('Lugar situado en el mapa', profile.last_known_place)
                        if state['case'] is None:
                            ui.button('BUSCAR CON ESTA REFERENCIA', icon='travel_explore',
                                      on_click=lambda: search_reference()).props('unelevated no-caps')
        reference_panel()

        # ── 03 · Resultados ─────────────────────────────────────────────────────────────
        @ui.refreshable
        def results_panel():
            summary = state['summary']
            if summary is None:
                return
            profile, case = state['profile'], state['case']
            with Panel('03 / Apariciones en cámaras', f'{summary["found"]} POSIBLE(S) · REVISIÓN HUMANA'):
                with ui.column().classes('p-4 w-full gap-3'):
                    ui.label(f'Se compararon {summary["captures"]} captura(s) con rostro — {summary["events"]} de '
                             f'eventos de auxilio, {summary["detections"]} detecciones de cámara y '
                             f'{summary["database"]} de la base compartida — y {summary["fichas"]} ficha(s).') \
                        .classes('text-xs muted')
                    if not state['results']:
                        EmptyState('Ninguna captura se parece lo suficiente a la referencia. Las cámaras en vivo '
                                   'seguirán comparando a esta persona si su ficha está registrada.')
                    for index, result in enumerate(state['results']):
                        ResultCard(index + 1, result, profile, case)
            if state['fichas']:
                with Panel('Fichas registradas parecidas', 'POSIBLE DUPLICADO · REVISAR'):
                    with ui.column().classes('p-4 w-full gap-2'):
                        for item in state['fichas']:
                            with ui.row().classes('items-center gap-3 w-full border-b border-[#edf0f2] py-2 no-wrap'):
                                photo = item['profile'].reference_photo or '/assets/demo/person-1.svg'
                                ui.image(photo).classes('w-12 h-14 rounded shrink-0').props('fit=cover')
                                with ui.column().classes('gap-0 flex-1'):
                                    ui.label(f'{item["case"].id} · {clean(item["case"].person.name)}') \
                                        .classes('text-sm font-medium')
                                    ui.label(f'Desaparición {item["case"].missing_date} · {item["case"].location}') \
                                        .classes('text-[11px] muted')
                                ui.label('Rostro').classes('text-[10px] muted')
                                LevelBadge(item['level'])
                                ui.button('Abrir ficha', on_click=lambda c=item['case']: ui.navigate.to(f'/cases/{c.id}')) \
                                    .props('flat dense no-caps')
                        ui.label('Dos fichas con rostros parecidos pueden ser la misma persona registrada dos '
                                 'veces. Verifícalo antes de unir expedientes.').classes('text-[10px] muted')
        results_panel()

        def ResultCard(order, result, profile, case):
            capture, camera = result['capture'], result['camera']
            ficha = ficha_side(case, profile, photo=None if case else (state['reference'] or {}).get('crop'))
            side = capture_side(capture.image, camera, capture.timestamp, capture.kind, capture.estimated_age,
                                capture.clothing_color, capture.label)
            with ui.expansion().classes('w-full border border-[#dce2e7] rounded-lg') \
                    .props('dense header-class="p-2"') as card:
                with card.add_slot('header'):
                    with ui.row().classes('items-center gap-3 w-full no-wrap'):
                        ui.label(str(order)).classes('order-chip')
                        ui.image(ficha['photo']).classes('w-10 h-12 rounded shrink-0').props('fit=cover')
                        ui.icon('compare_arrows', size='16px', color='blue-grey-4')
                        ui.image(side['image']).classes('w-10 h-12 rounded shrink-0').props('fit=cover')
                        with ui.column().classes('gap-0 flex-1 min-w-0'):
                            ui.label(f'{side["camera"]} · {capture.timestamp}').classes('text-xs font-medium')
                            ui.label(SOURCE_LABELS.get(capture.kind, capture.kind)
                                     + (f' · {capture.label}' if capture.label else '')).classes('text-[10px] muted')
                        ui.label('Rostro').classes('text-[10px] muted')
                        LevelBadge(result['level'])
                        ui.label('Prioridad').classes('text-[10px] muted')
                        LevelBadge(result['priority'])
                with ui.column().classes('p-3 w-full gap-0'):
                    FaceComparison(ficha, side, result['signals'], priority=result['priority'])
                    with ui.row().classes('gap-2 mt-3 flex-wrap'):
                        if case is not None and can('cases.manage'):
                            ui.button('ENVIAR A REVISIÓN DEL CASO', icon='fact_check',
                                      on_click=lambda c=capture: notify_action(
                                          lambda: promote_result(profile, c),
                                          'Enviado a la cola de revisión del caso.')).props('unelevated no-caps')
                        if capture.event_id and can('alerts.view'):
                            ui.button('Ver evidencia del evento', icon='videocam',
                                      on_click=lambda c=capture: ui.navigate.to(f'/alerts?event_id={c.event_id}')) \
                                .props('outline no-caps')
                        if case is not None:
                            ui.button('Ver trayecto', icon='route',
                                      on_click=lambda: ui.navigate.to(f'/tracking?case_id={case.id}')) \
                                .props('flat no-caps')
                    if case is None:
                        ui.label('Para enviarlo a revisión, registra primero la ficha como caso (Casos de búsqueda '
                                 '→ Crear caso desde alerta).').classes('text-[10px] muted mt-1')

        # ── acciones ────────────────────────────────────────────────────────────────────
        def busy(on, message=None):
            state['busy'] = on
            spinner.set_visibility(on)
            if message:
                status.set_text(message)

        async def get_model():
            try:
                require('cases.import')
            except PermissionError as error:
                ui.notify(str(error), type='warning')
                return
            busy(True, 'Descargando y cargando el modelo facial (una sola vez, puede tardar unos minutos)…')
            try:
                await run.io_bound(searcher.download_model)
                ready, message = searcher.model_status()
                engine_label.set_text(message)
                download.set_visibility(not ready)
                ui.notify('Modelo facial listo.', type='positive')
            except Exception as error:
                ui.notify(f'No fue posible descargar el modelo: {error}', type='negative', multi_line=True)
            finally:
                busy(False, 'Elige una ficha registrada o sube una referencia.')

        async def execute(profile):
            actor = require('matches.view') if can('matches.view') else require('cases.import')
            busy(True, 'Comparando con las capturas de las cámaras y las fichas registradas…')
            try:
                results, fichas, summary = await run.io_bound(searcher.run_reference_search, profile, actor)
                state.update(results=results, fichas=fichas, summary=summary)
                status.set_text(f'Búsqueda terminada: {summary["found"]} aparición(es) posible(s) en cámaras. '
                                'Todo queda pendiente de revisión humana.')
            finally:
                busy(False)
                results_panel.refresh()

        async def search_registered():
            if state['busy'] or not case_select.value:
                if not case_select.value:
                    ui.notify('Elige una ficha registrada.', type='warning')
                return
            case = get_case(case_select.value)
            profile = await run.io_bound(ensure_profile, case)
            state.update(profile=profile, case=case, reference=None, summary=None)
            reference_panel.refresh()
            results_panel.refresh()
            if not profile.face_embedding:
                status.set_text(f'La ficha no tiene una huella facial utilizable: {profile.face_message}')
                ui.notify(profile.face_message or 'La ficha no tiene una fotografía con rostro.', type='warning')
                return
            await execute(profile)

        async def upload(event):
            if not consent.value:
                ui.notify('Confirma que la imagen está autorizada para la búsqueda.', type='warning')
                uploader.reset()
                return
            try:
                actor = require('cases.import')
                content = await event.file.read()
                busy(True, 'Analizando la referencia…')
                if kind.value == 'ficha':
                    from services.alert_import_service import analyze_alert, save_upload
                    record_id, path, detected = await run.io_bound(save_upload, content, event.file.content_type,
                                                                   event.file.name, actor)
                    record = await run.io_bound(analyze_alert, record_id, path, detected, actor)
                    if not record.photo_path:
                        raise searcher.ReferenceError_('No se pudo recortar la fotografía de la ficha.')
                    image = str(config.BASE_DIR / record.photo_path)
                    declared = {'name': record.person_name or '', 'age': record.age or '',
                                'missing_date': record.date_of_disappearance or '',
                                'location': record.location_of_events or '',
                                'clothing': record.clothing_description or '', 'marks': record.distinctive_marks or ''}
                else:
                    image = str(await run.io_bound(searcher.save_reference_image, content, event.file.content_type))
                    declared = {'name': 'Referencia autorizada'}
                ready, message = searcher.model_status()
                if not ready:
                    raise searcher.ReferenceError_(message)
                reference = await run.io_bound(searcher.face_reference, image)
                profile = profile_from_reference(reference['embedding'], photo=reference['crop'],
                                                 source='FICHA' if kind.value == 'ficha' else 'FOTOGRAFIA_AUTORIZADA',
                                                 **declared)
                state.update(profile=profile, case=None, reference=reference, summary=None)
                status.set_text('Referencia lista. Revisa los datos declarados y pulsa BUSCAR CON ESTA REFERENCIA.')
            except (ValueError, PermissionError) as error:
                status.set_text(str(error))
                ui.notify(str(error), type='warning', multi_line=True)
            except Exception as error:
                status.set_text('No fue posible analizar la imagen.')
                ui.notify(f'No fue posible analizar la imagen: {error}', type='negative')
            finally:
                busy(False)
                uploader.reset()
                reference_panel.refresh()
                results_panel.refresh()

        async def search_reference():
            profile = state['profile']
            if profile is None or state['busy']:
                return
            values = {key: field.value for key, field in state['fields'].items()}
            profile = profile_from_reference(profile.face_embedding, photo=profile.reference_photo,
                                             source=profile.notes, **values)
            state['profile'] = profile
            await execute(profile)

        if case_id and get_case(case_id):
            ui.timer(.1, search_registered, once=True)
