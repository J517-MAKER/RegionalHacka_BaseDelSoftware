from nicegui import ui
from components.layout import PageLayout,guard_page
from components.search_filters import SearchFilters
from components.case_form import NewCaseDialog
from components.states import EmptyState
from services.cases_service import get_cases
from services.tracking_service import get_tracking_history
from services.users_service import can


@ui.page('/cases')
def cases_page():
    if not guard_page('/cases', 'cases.view'):
        return
    with PageLayout('/cases','Casos de búsqueda','Registro y consulta de expedientes de personas desaparecidas.'):
        fields={}
        @ui.refreshable
        def case_table():
            rows=[]
            query=(fields['query'].value or '').lower()
            for case in get_cases():
                if query not in (case.person.name+' '+case.id).lower():
                    continue
                if fields['status'].value not in ('Todos',case.status) or fields['zone'].value not in ('Todas',case.zone) or fields['owner'].value not in ('Todos',case.owner):
                    continue
                if fields['date'].value and not case.reported_at.startswith(fields['date'].value):
                    continue
                history=get_tracking_history(case.id)
                rows.append({'id':case.id,'name':case.person.name,'date':case.reported_at,'location':case.location,'status':case.status,
                             'last':history[-1].detection.timestamp[11:]+' · '+history[-1].detection.camera_id if history else 'Sin detecciones','owner':case.owner})
            if not rows:
                EmptyState()
                return
            columns=[{'name':key,'label':label,'field':key,'align':'left','sortable':True} for key,label in [('id','Folio'),('name','Nombre'),('date','Fecha del reporte'),('location','Último lugar conocido'),('status','Estado'),('last','Última detección'),('owner','Responsable')]]
            columns.append({'name':'actions','label':'Acciones','field':'id','align':'left'})
            table=ui.table(columns=columns,rows=rows,row_key='id',pagination=10).classes('w-full')
            table.add_slot('body-cell-actions','<q-td :props="props"><q-btn flat dense no-caps color="primary" label="Abrir caso" @click="$parent.$emit(\'open\', props.row.id)" /></q-td>')
            table.on('open',lambda e:ui.navigate.to(f'/cases/{e.args}'))
        with ui.row().classes('items-center justify-between w-full'):
            ui.label('EXPEDIENTES / DATOS DE PRUEBA').classes('eyebrow')
            # Registering a case is operational work: supervisor and administrator only consult.
            with ui.row().classes('gap-2'):
                if can('cases.import'):
                    ui.button('Crear caso desde alerta',icon='document_scanner',on_click=lambda:ui.navigate.to('/cases/import-alert')).props('unelevated no-caps')
                if can('cases.manage'):
                    ui.button('Nueva búsqueda manual',icon='add',on_click=lambda:NewCaseDialog()).props('outline no-caps')
        fields.update(SearchFilters(lambda:case_table.refresh(),statuses=['En búsqueda','Pausada'],zones=sorted({c.zone for c in get_cases()}),owners=sorted({c.owner for c in get_cases()}),with_date=True))
        case_table()
