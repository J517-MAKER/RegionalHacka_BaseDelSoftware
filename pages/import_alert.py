from nicegui import ui, run
from components.layout import PageLayout,Panel,notify_action,guard_page
from components.alert_preview import DocumentPreview, ExtractedPhoto, ExtractionStatus, MatchBlocks
from models.alert_import_record import EDITABLE_FIELDS, LONG_FIELDS
from services.alert_import_service import (analyze_alert, cancel_import, create_case_from_alert, link_to_case,
                                           run_matching, save_upload, send_to_review, update_fields)
from services.cases_service import get_cases
from services.users_service import can, require


@ui.page('/cases/import-alert')
def import_alert_page():
    if not guard_page('/cases', 'cases.import'):
        return
    with PageLayout('/cases', 'Importar alerta de búsqueda',
                    'Cargar una ficha de búsqueda para extraer información y generar un caso.'):
        state = {'record': None, 'fields': {}}

        @ui.refreshable
        def workspace():
            record = state['record']
            with ui.element('div').classes('workspace-grid'):
                with ui.column().classes('w-full gap-5 min-w-0'):
                    with Panel('02 / Vista previa del documento'):
                        with ui.column().classes('p-4 w-full'):
                            DocumentPreview(record)
                with ui.element('div').classes('stack'):
                    with Panel('03 / Fotografía extraída'):
                        with ui.column().classes('p-4 w-full'):
                            ExtractedPhoto(record)
            if not record:
                return
            with Panel('04 / Datos extraídos y editables'):
                with ui.column().classes('p-4 w-full gap-3'):
                    ExtractionStatus(record)
                    ui.label('La lectura automática puede equivocarse. Corrige los campos antes de continuar.') \
                        .classes('text-xs muted')
                    state['fields'] = {}
                    with ui.element('div').classes('field-grid'):
                        for key, label in EDITABLE_FIELDS:
                            value = getattr(record, key) or ''
                            field = (ui.textarea(label, value=value).props('outlined autogrow')
                                     if key in LONG_FIELDS else ui.input(label, value=value).props('outlined dense'))
                            field.set_enabled(can('cases.import'))
                            state['fields'][key] = field
                    with ui.row().classes('gap-2'):
                        ui.button('Guardar correcciones', icon='save', on_click=save_edits) \
                            .props('outline no-caps').set_enabled(can('cases.import'))
                        ui.button('Analizar coincidencias', icon='travel_explore', on_click=match) \
                            .props('unelevated no-caps').set_enabled(can('cases.import'))
                    if record.ocr_text:
                        with ui.expansion('Ver texto leído del documento').classes('w-full'):
                            ui.label(record.ocr_text).classes('text-xs whitespace-pre-wrap muted')
            if record.text_match_status != 'PENDIENTE':
                with Panel('05 / Coincidencias encontradas'):
                    with ui.column().classes('p-4 w-full gap-1'):
                        MatchBlocks(record, on_link=link)
            with Panel('06 / Acciones finales'):
                with ui.column().classes('p-4 w-full gap-3'):
                    if record.linked_case_id:
                        ui.label(f'Alerta vinculada al caso {record.linked_case_id} · {record.review_status}') \
                            .classes('text-sm')
                        ui.button('Abrir caso', icon='folder_open',
                                  on_click=lambda: ui.navigate.to(f'/cases/{record.linked_case_id}')) \
                            .props('unelevated no-caps')
                    else:
                        with ui.row().classes('gap-2 flex-wrap'):
                            ui.button('Crear caso nuevo', icon='add', on_click=create) \
                                .props('unelevated no-caps').set_enabled(can('cases.import'))
                            ui.button('Vincular con caso existente', icon='link', on_click=link_dialog) \
                                .props('outline no-caps').set_enabled(can('cases.import'))
                            ui.button('Enviar a revisión', icon='fact_check', on_click=review) \
                                .props('outline no-caps').set_enabled(can('cases.import'))
                            ui.button('Cancelar importación', icon='close', on_click=cancel) \
                                .props('flat no-caps').set_enabled(can('cases.import'))
                        ui.label('Crear o vincular no confirma la identidad de la persona: el expediente queda '
                                 'pendiente de validación.').classes('text-xs muted')

        async def upload(event):
            try:
                actor = require('cases.import')  # the session is not readable inside run.io_bound threads
                content = await event.file.read()
                record_id, path, kind = await run.io_bound(save_upload, content, event.file.content_type,
                                                           event.file.name, actor)
                status.set_text('Analizando la ficha (OCR y recorte de fotografía)…')
                spinner.set_visibility(True)
                state['record'] = await run.io_bound(analyze_alert, record_id, path, kind, actor)
                status.set_text('Ficha analizada. Revisa los datos extraídos.')
                ui.notify('Alerta analizada correctamente.', type='positive', position='bottom-right')
            except (ValueError, PermissionError) as error:
                status.set_text(str(error))
                ui.notify(str(error), type='warning', position='bottom-right')
            except Exception:
                status.set_text('No fue posible analizar el archivo. Intenta con otra imagen o PDF.')
                ui.notify('No fue posible analizar el archivo.', type='negative', position='bottom-right')
            finally:
                spinner.set_visibility(False)
                workspace.refresh()

        def collect():
            return {key: field.value for key, field in state['fields'].items()}

        def save_edits():
            notify_action(lambda: update_fields(state['record'].id, collect()),
                          'Correcciones guardadas.', workspace.refresh)

        async def match():
            update_fields(state['record'].id, collect())
            actor = require('cases.import')
            status.set_text('Comparando con casos, cámaras y rango temporal…')
            spinner.set_visibility(True)
            try:
                await run.io_bound(run_matching, state['record'].id, actor)
                status.set_text('Comparación terminada. Todo queda pendiente de validación humana.')
            finally:
                spinner.set_visibility(False)
                workspace.refresh()

        def create():
            case = notify_action(lambda: create_case_from_alert(state['record'].id),
                                 'Caso creado desde la alerta. Pendiente de validación.', workspace.refresh)
            if case:
                ui.navigate.to(f'/cases/{case.id}')

        def link(case_id):
            notify_action(lambda: link_to_case(state['record'].id, case_id),
                          f'Alerta vinculada al caso {case_id}.', workspace.refresh)

        def link_dialog():
            with ui.dialog() as dialog, ui.card().classes('w-96 p-6'):
                ui.label('Vincular con caso existente').classes('section-title')
                selector = ui.select({c.id: f'{c.id} · {c.person.name}' for c in get_cases()},
                                     label='Caso').props('outlined dense').classes('w-full')
                with ui.row().classes('justify-end w-full'):
                    ui.button('Cancelar', on_click=dialog.close).props('flat no-caps')

                    def confirm():
                        if selector.value:
                            link(selector.value)
                            dialog.close()
                    ui.button('Vincular', on_click=confirm).props('unelevated no-caps')
            dialog.open()

        def review():
            notify_action(lambda: send_to_review(state['record'].id),
                          'Alerta enviada a revisión.', workspace.refresh)

        def cancel():
            def action():
                cancel_import(state['record'].id)
                state['record'] = None
            notify_action(action, 'Importación cancelada. Los archivos temporales se eliminaron.', workspace.refresh)

        with Panel('01 / Carga de archivo'):
            with ui.column().classes('p-4 w-full gap-2'):
                ui.label('Formatos admitidos: JPG, PNG, WebP o PDF de hasta 10 MB. El archivo se conserva de forma '
                         'temporal únicamente para esta importación.').classes('text-xs muted')
                uploader = ui.upload(label='Seleccionar ficha de búsqueda', on_upload=upload, auto_upload=True,
                                     max_files=1, max_file_size=10 * 1024 * 1024,
                                     on_rejected=lambda: ui.notify('Archivo rechazado. Revisa el formato y el límite de 10 MB.',
                                                                   type='warning')) \
                    .props('accept=.png,.jpg,.jpeg,.webp,.pdf flat bordered').classes('w-full')
                uploader.set_enabled(can('cases.import'))
                with ui.row().classes('items-center gap-3'):
                    spinner = ui.spinner(size='18px')
                    spinner.set_visibility(False)
                    status = ui.label('Selecciona una ficha para comenzar.').classes('text-sm')
                ui.label('La lectura automática es un apoyo: no confirma identidades ni localizaciones.') \
                    .classes('text-xs muted')
        workspace()
