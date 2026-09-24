from dataclasses import asdict
from nicegui import ui
from components.layout import PageLayout,guard_page
from components.states import EmptyState
from services.history_service import SCOPE_TITLES,current_scope,get_history

KIND_FILTERS = {'operational': ['Todos','Coincidencia','Búsqueda','Revisión','Voz','Alerta','Seguimiento',
                                'Cámara','Importación','Evidencia'],
                'supervision': ['Todos','Revisión','Evidencia','Coincidencia','Seguimiento','Búsqueda','Voz',
                                'Alerta','Importación','Cámara'],
                'full': ['Todos','Sesión','Permisos','Configuración','Comando de voz','Búsqueda','Cámara',
                         'Coincidencia','Revisión','Evidencia','Seguimiento','Importación','Voz','Alerta']}


@ui.page('/history')
def history_page():
    if not guard_page('/history', 'history.operational', 'audit.operational', 'audit.full'):
        return
    # One page, three depths: the scope comes from the role, not from a query parameter.
    scope = current_scope()
    title, subtitle = SCOPE_TITLES[scope]
    with PageLayout('/history',title,subtitle):
        @ui.refreshable
        def table():
            records=get_history(scope)
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
            kind=ui.select(KIND_FILTERS[scope],value='Todos',label='Tipo',on_change=lambda:table.refresh()).props('outlined dense')
            date=ui.input('Fecha',on_change=lambda:table.refresh()).props('outlined dense type=date stack-label clearable')
            ui.button('Actualizar',icon='refresh',on_click=lambda:table.refresh()).props('outline no-caps')
        table()
        if scope!='full':
            ui.label('Las acciones de administración de usuarios y de configuración se registran en la '
                     'auditoría completa del administrador.').classes('text-xs muted')
