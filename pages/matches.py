from nicegui import ui
from components.layout import PageLayout
from components.match_comparison import MatchComparison
from components.status_badge import StatusBadge
from components.states import EmptyState
from services.facial_service import get_matches,get_detection
from services.cases_service import get_cases


@ui.page('/matches')
def matches_page(case_id:str='',match_id:str=''):
    selected={'id':match_id}
    with PageLayout('/matches','Revisión de coincidencias','Comparación de referencias y capturas para validación por un operador autorizado.'):
        @ui.refreshable
        def content():
            matches=[m for m in get_matches(case_filter.value or None) if state.value=='Todas' or m.status==state.value]
            if not matches:
                EmptyState('No hay coincidencias para esta selección.')
                return
            match=next((m for m in matches if m.id==selected['id']),matches[0])
            selected['id']=match.id
            with ui.element('div').classes('detail-grid review-grid'):
                with ui.element('section').classes('panel'):
                    ui.label(f'{len(matches)} coincidencias').classes('panel-heading section-title')
                    for item in matches:
                        d=get_detection(item.detection_id)
                        def select(mid=item.id):
                            selected['id']=mid
                            content.refresh()
                        with ui.element('div').classes('review-list-item '+('selected' if item.id==match.id else '')).on('click',select):
                            with ui.row().classes('justify-between w-full mb-2'):
                                ui.label(d.camera_id).classes('mono')
                                ui.label(f'{d.similarity} %').classes('text-sm font-medium')
                            ui.label(d.case_id).classes('text-xs muted mb-2')
                            ui.label(d.timestamp).classes('text-[10px] muted mb-3')
                            StatusBadge(item.status)
                with ui.column().classes('panel p-6 gap-0'):
                    MatchComparison(match,content.refresh)
        with ui.element('div').classes('toolbar'):
            options={'':'Todos los casos',**{c.id:f'{c.id} · {c.person.name}' for c in get_cases()}}
            case_filter=ui.select(options,value=case_id if case_id in options else '',label='Caso',on_change=lambda:content.refresh()).props('outlined dense')
            state=ui.select(['Todas','Pendiente de validación','En revisión','Validada por operador','Descartada'],value='Todas',label='Estado de revisión',on_change=lambda:content.refresh()).props('outlined dense')
        content()
