from nicegui import ui
from components.layout import PageLayout,Panel,guard_page
from components.person_profile import PersonProfile
from components.map_view import MapView
from components.timeline import Timeline
from components.states import ErrorState
from services.cases_service import get_case,add_case_photo
from services.users_service import can
from services.tracking_service import get_tracking_history
from services.facial_service import get_matches


@ui.page('/cases/{case_id}')
def case_detail_page(case_id:str):
    if not guard_page('/cases', 'cases.view'):
        return
    case=get_case(case_id)
    with PageLayout('/cases','Detalle del caso',case_id):
        ui.link('← Volver a casos de búsqueda','/cases').classes('text-xs no-underline')
        if not case:
            ErrorState('No se encontró este expediente.')
            return
        events=get_tracking_history(case_id)
        def review(detection_id):
            match=next((m for m in get_matches(case_id) if m.detection_id==detection_id),None)
            if match:
                ui.navigate.to(f'/matches?case_id={case_id}&match_id={match.id}')
            else:
                from components.detection_detail import DetectionDetail
                DetectionDetail(detection_id)
        with ui.element('div').classes('detail-grid'):
            with ui.column().classes('w-full gap-3'):
                @ui.refreshable
                def profile():
                    PersonProfile(case)
                profile()
                async def upload(event):
                    try:
                        add_case_photo(case_id,await event.file.read(),event.file.content_type)
                        profile.refresh()
                        ui.notify('Fotografía de referencia añadida.',type='positive')
                    except (ValueError,PermissionError) as error:
                        ui.notify(str(error),type='warning')
                if can('cases.manage'):
                    ui.upload(label='Añadir referencia de prueba',on_upload=upload,auto_upload=True,max_file_size=5*1024*1024,
                              on_rejected=lambda:ui.notify('Imagen rechazada. Máximo 5 MB.',type='warning')).props('accept=.png,.jpg,.jpeg,.webp flat bordered').classes('w-full')
            with ui.column().classes('w-full gap-5'):
                with Panel('Mapa de detecciones',f'{len(events)} DETECCIONES'):
                    MapView(detections=events,height=350)
                with Panel('Secuencia de detecciones','REVISIÓN INDIVIDUAL'):
                    with ui.column().classes('panel-body'):
                        Timeline(events,on_review=review)
                ui.button('Abrir seguimiento completo',icon='route',on_click=lambda:ui.navigate.to(f'/tracking?case_id={case_id}')).props('outline no-caps')
