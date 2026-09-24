# pyrefly: ignore [missing-import]
from nicegui import ui
from components.layout import PageLayout,Panel,guard_page
from components.map_view import MapView,update_map
from components.activity_log import ActivityLog
from components.camera_feed import CameraFeed
from components.status_badge import StatusBadge
from services.cases_service import get_active_cases
from services.cameras_service import get_cameras
from services.facial_service import get_matches
from services.evidence_service import get_evidence
from services.history_service import get_history


@ui.page('/monitor')
def monitor_page():
    if not guard_page('/monitor', 'monitor.view'):
        return
    with PageLayout('/monitor','Centro de monitoreo','Supervisión de búsquedas, cámaras y eventos pendientes de revisión.'):
        @ui.refreshable
        def stats():
            cases,cameras=get_active_cases(),get_cameras()
            pending=sum(m.status in ('Pendiente de validación','En revisión') for m in get_matches())
            alerts=sum(e.review_status in ('PENDIENTE_REVISION','EN_REVISION') for e in get_evidence())
            with ui.element('div').classes('stat-strip'):
                for value,label,detail in [(len(cases),'Casos activos','Búsquedas en curso'),
                                           (f'{sum(c.status!="Desconectada" for c in cameras)}/{len(cameras)}','Cámaras conectadas','Red de demostración'),
                                           (pending,'Coincidencias pendientes','Requieren validación humana'),(alerts,'Evidencia por revisar','Posibles solicitudes de auxilio')]:
                    with ui.element('div').classes('stat-item'):
                        ui.label(str(value)).classes('stat-value')
                        with ui.column().classes('gap-0'):
                            ui.label(label).classes('stat-label')
                            ui.label(detail).classes('stat-detail')

        @ui.refreshable
        def camera_tiles():
            cameras=get_cameras()
            with ui.element('div').classes('camera-grid').style('grid-template-columns:repeat(3,minmax(0,1fr))'):
                for cid in ('CAM-003','CAM-007','CAM-008'):
                    CameraFeed(next(c for c in cameras if c.id==cid),lambda camera_id:ui.navigate.to(f'/cameras?camera_id={camera_id}'))

        @ui.refreshable
        def side():
            cases=get_active_cases()
            with Panel('Actividad reciente','BITÁCORA'):
                ActivityLog(get_history(),5)
                ui.link('Consultar historial completo →','/history').classes('text-[11px] no-underline px-4 py-3 block border-t border-[#edf0f2]')
            with Panel('Casos activos',f'{len(cases)} EN BÚSQUEDA'):
                for case in cases:
                    with ui.link(target=f'/cases/{case.id}').classes('case-row no-underline text-inherit'):
                        ui.image(case.person.photos[0] if case.person.photos else '/assets/demo/person-1.svg').classes('case-thumb')
                        with ui.column().classes('gap-1'):
                            ui.label(case.person.name.replace(' (ficticia)','').replace(' (ficticio)','')).classes('text-xs font-medium')
                            ui.label(case.id).classes('mono muted')
                        ui.space()
                        ui.icon('chevron_right',size='15px',color='blue-grey-4')
            with ui.row().classes('page-note items-start'):
                ui.icon('info_outline',size='16px')
                ui.label('Datos y capturas ficticios. Las detecciones apoyan la revisión del operador.').classes('flex-1')

        def refresh():
            stats.refresh()
            camera_tiles.refresh()
            side.refresh()
            update_map(coverage)  # the map is not rebuilt: only its markers change

        stats()
        with ui.element('div').classes('workspace-grid mt-5'):
            with ui.column().classes('w-full gap-5 min-w-0'):
                with Panel('Cobertura de cámaras','MAPA INTERACTIVO · MAPBOX'):
                    with ui.row().classes('px-4 py-2 items-center justify-between w-full border-b border-[#e5eaee]'):
                        ui.label('Región Centro').classes('text-xs font-medium')
                        with ui.row().classes('gap-1'):
                            ui.button('Abrir seguimiento',icon='open_in_full',on_click=lambda:ui.navigate.to('/tracking')).props('flat dense no-caps size=sm')
                            ui.button(icon='refresh',on_click=refresh).props('flat dense').tooltip('Actualizar información')
                    coverage=MapView(get_cameras())
                with ui.row().classes('items-center justify-between w-full -mb-2'):
                    ui.label('Cámaras de interés').classes('section-title')
                    ui.link('Ver todas las cámaras →','/cameras').classes('text-xs no-underline')
                camera_tiles()
            with ui.element('div').classes('stack'):
                side()
        ui.timer(15,refresh)
