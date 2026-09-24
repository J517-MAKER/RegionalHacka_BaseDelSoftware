from nicegui import ui
from components.layout import PageLayout,Panel,notify_action
from services.settings_service import get_settings,save_settings
from services.users_service import can


@ui.page('/settings')
def settings_page():
    with PageLayout('/settings','Configuración','Preferencias de demostración y puntos de integración del sistema.'):
        ui.label('Valores de referencia guardados en memoria. Los conectores reales, las políticas de sesión y los umbrales no se ejecutan en esta demo.').classes('notice')
        settings=get_settings()
        with ui.tabs().classes('w-full border-b border-[#dce2e7]') as tabs:
            sections={name:ui.tab(name) for name in settings}
        with ui.tab_panels(tabs,value=sections['General']).classes('w-full'):
            for name,values in settings.items():
                with ui.tab_panel(sections[name]):
                    with Panel(name,'PREFERENCIAS DE DEMOSTRACIÓN'):
                        with ui.column().classes('panel-body gap-4 max-w-2xl'):
                            fields={}
                            for key,value in values.items():
                                if isinstance(value,bool):
                                    field=ui.switch(key,value=value)
                                elif isinstance(value,int):
                                    field=ui.number(key,value=value,min=1,max=10000).props('outlined dense')
                                else:
                                    field=ui.input(key,value=value).props('outlined dense')
                                field.classes('w-full')
                                field.set_enabled(can('settings') and name not in ('Integraciones','Voz'))
                                fields[key]=field
                            if name not in ('Integraciones','Voz'):
                                ui.button('Guardar cambios',on_click=lambda n=name,f=fields:notify_action(lambda:save_settings(n,{k:v.value for k,v in f.items()}),'Configuración guardada.')).props('unelevated no-caps').set_enabled(can('settings'))
                            if name=='Integraciones':
                                for service,label in [('cases_service.py','Casos y reportes'),('cameras_service.py','Cámaras y estado de red'),('facial_service.py','Reconocimiento y validación'),('tracking_service.py','Reidentificación y seguimiento'),('voice_service.py','Transcripción e intenciones'),('alerts_service.py','Recepción y revisión de eventos')]:
                                    with ui.row().classes('w-full py-2 border-b border-[#edf0f2] justify-between'):
                                        ui.label(label).classes('text-xs')
                                        ui.label(service).classes('mono muted')
                            if not can('settings'):
                                ui.label('Consulta disponible. Para editar, usa una sesión de Supervisor o Administrador.').classes('text-xs muted')
