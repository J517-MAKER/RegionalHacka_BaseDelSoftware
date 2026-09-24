from nicegui import ui
from components.layout import PageLayout,Panel,guard_page
from components.candidate_review import CandidateReview, CandidateRow
from components.match_comparison import MatchComparison
from components.status_badge import StatusBadge
from components.states import EmptyState
from services.facial_service import get_matches,get_detection
from services.face_engine import display_level
from services.cases_service import get_cases
from services.search_matching_service import get_candidates


@ui.page('/matches')
def matches_page(case_id:str='',match_id:str='',review:str=''):
    if not guard_page('/matches', 'matches.view'):
        return
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
                                ui.label(display_level(d.similarity)).classes('text-sm font-medium')
                            ui.label(d.case_id).classes('text-xs muted mb-2')
                            ui.label(d.timestamp).classes('text-[10px] muted mb-3')
                            StatusBadge(item.status)
                with ui.column().classes('panel p-6 gap-0'):
                    MatchComparison(match,content.refresh)
        with ui.element('div').classes('toolbar'):
            options={'':'Todos los casos',**{c.id:f'{c.id} · {c.person.name}' for c in get_cases()}}
            case_filter=ui.select(options,value=case_id if case_id in options else '',label='Caso',on_change=lambda:content.refresh()).props('outlined dense')
            states=['Todas','Pendiente de validación','En revisión','Validada por operador','Descartada']
            # A supervisor arrives from the sidebar already filtered to what was escalated.
            state=ui.select(states,value=review if review in states else 'Todas',label='Estado de revisión',on_change=lambda:content.refresh()).props('outlined dense')
        content()

        # Candidatos del motor de búsqueda: la ficha comparada con las detecciones guardadas.
        selected_candidate={'id':None}

        @ui.refreshable
        def candidates():
            pending=[c for c in get_candidates(case_filter.value or None)
                     if c.status in ('AI_CANDIDATE','PENDING_HUMAN_REVIEW')]
            if not pending:
                return
            with Panel('Candidatos del motor de búsqueda',
                       f'{len(pending)} PARA REVISIÓN HUMANA · IDENTIDAD NO CONFIRMADA'):
                with ui.column().classes('p-4 w-full gap-2'):
                    for candidate in pending:
                        CandidateRow(candidate,on_open=open_candidate)
        def open_candidate(candidate):
            selected_candidate['id']=candidate.candidate_match_id
            detail.refresh()
            candidate_drawer.show()
        with ui.right_drawer(value=False).props('width=560 bordered overlay').classes('p-0') as candidate_drawer:
            @ui.refreshable
            def detail():
                from services.search_matching_service import get_candidate
                candidate=get_candidate(selected_candidate['id'])
                if not candidate:
                    return
                with ui.row().classes('panel-heading w-full'):
                    ui.label(candidate.candidate_match_id).classes('section-title')
                    ui.button(icon='close',on_click=candidate_drawer.hide).props('flat dense round')
                with ui.column().classes('p-5 w-full gap-0'):
                    CandidateReview(candidate,on_change=lambda:(detail.refresh(),candidates.refresh()))
            detail()
        candidates()
