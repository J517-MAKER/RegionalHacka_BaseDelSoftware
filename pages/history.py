from dataclasses import asdict
from nicegui import ui
from components.layout import PageLayout
from components.states import EmptyState
from services.history_service import get_history


@ui.page('/history')
def history_page():
    with PageLayout('/history','Historial de operaciones','Bitácora de acciones, detecciones y revisiones. Cada decisión conserva al usuario responsable.'):
        @ui.refreshable
        def table():
            records=get_history()
            if search.value:
                records=[r for r in records if search.value.lower() in ' '.join(str(v) for v in asdict(r).values()).lower()]
            if kind.value!='Todos':
                records=[r for r in records if r.kind==kind.value]
            if date.value:
                records=[r for r in records if r.timestamp.startswith(date.value)]
            if not records:
                EmptyState()
                return
            columns=[{'name':key,'field':key,'label':label,'align':'left','sortable':True} for key,label in [('timestamp','Fecha y hora'),('user','Usuario'),('kind','Tipo'),('description','Descripción'),('case_id','Caso relacionado'),('camera_id','Cámara'),('result','Resultado')]]
            ui.table(columns=columns,rows=[dict(id=i,**asdict(r)) for i,r in enumerate(records)],row_key='id',pagination=12).classes('w-full')
        with ui.element('div').classes('toolbar'):
            search=ui.input('Buscar usuario, caso o descripción',on_change=lambda:table.refresh()).props('outlined dense clearable')
            kind=ui.select(['Todos','Coincidencia','Búsqueda','Revisión','Voz','Alerta','Seguimiento','Comando de voz','Sesión','Configuración','Permisos'],value='Todos',label='Tipo',on_change=lambda:table.refresh()).props('outlined dense')
            date=ui.input('Fecha',on_change=lambda:table.refresh()).props('outlined dense type=date stack-label clearable')
            ui.button('Actualizar',icon='refresh',on_click=lambda:table.refresh()).props('outline no-caps')
        table()
