from nicegui import ui
from components.layout import notify_action
from services.cases_service import create_case,photo_data_url


def NewCaseDialog(on_created=None,photos=None,navigate=True):
    """photos: data URLs already taken (for example, from the live camera); navigate: open the new case."""
    fields={}
    photos=list(photos or [])
    with ui.dialog() as dialog,ui.card().classes('app-dialog p-0 gap-0'):
        with ui.row().classes('panel-heading w-full'):
            ui.label('Nueva búsqueda').classes('text-lg font-medium')
            ui.button(icon='close',on_click=dialog.close).props('flat dense round')
        with ui.column().classes('p-6 w-full gap-3'):
            ui.label('Utiliza datos de prueba. Los campos no conocidos pueden dejarse vacíos.').classes('text-xs muted')
            def section(title,spec):
                ui.label(title).classes('form-section')
                with ui.element('div').classes('field-grid'):
                    for key,label,kind in spec:
                        field=ui.input(label).props('outlined dense') if kind!='textarea' else ui.textarea(label).props('outlined autogrow')
                        if kind in ('date','time','number'):
                            field.props(f'type={kind} stack-label')
                        fields[key]=field
            section('01 / Datos principales',[('name','Nombre completo *','text'),('age','Edad','number'),('sex','Sexo registrado en el reporte','text'),('missing_date','Fecha de desaparición','date'),('missing_time','Hora aproximada','time')])
            ui.label('02 / Fotografías de referencia').classes('form-section')
            previews=ui.row().classes('gap-2')
            with previews:
                for source in photos:
                    ui.image(source).classes('w-16 h-20').props('fit=contain')
            async def upload(event):
                try:
                    if len(photos)>=5:
                        raise ValueError('Máximo cinco fotografías por caso.')
                    source=photo_data_url(await event.file.read(),event.file.content_type)
                    photos.append(source)
                    with previews:
                        ui.image(source).classes('w-16 h-20').props('fit=contain')
                    ui.notify('Fotografía de referencia añadida.',position='bottom-right')
                except ValueError as error:
                    ui.notify(str(error),type='warning')
            ui.upload(label='Añadir fotografías · máximo 5 MB por imagen',on_upload=upload,multiple=True,max_files=5,max_file_size=5*1024*1024,
                      auto_upload=True,on_rejected=lambda:ui.notify('Archivo rechazado. Revisa el formato y el límite de 5 MB.',type='warning')).props('accept=.png,.jpg,.jpeg,.webp flat bordered').classes('w-full')
            section('03 / Características físicas',[('height','Estatura aproximada','text'),('build','Complexión','text'),('skin','Tono de piel registrado','text'),('hair','Color de cabello','text'),('eyes','Color de ojos','text'),('clothing','Vestimenta','textarea'),('marks','Señas particulares','textarea')])
            section('04 / Última ubicación conocida',[('location','Lugar o dirección','text'),('zone','Zona','text')])
            section('05 / Información del reporte',[('description','Descripción adicional','textarea')])
            def submit():
                data={key:field.value for key,field in fields.items()}
                data['photos']=photos
                case=notify_action(lambda:create_case(data),'Caso registrado correctamente.')
                if case:
                    dialog.close()
                    if on_created:
                        on_created()
                    if navigate:
                        ui.navigate.to(f'/cases/{case.id}')
            with ui.row().classes('w-full justify-end mt-4'):
                ui.button('Cancelar',on_click=dialog.close).props('flat no-caps')
                ui.button('Registrar caso y procesar referencias',on_click=submit).props('unelevated no-caps')
    dialog.open()
