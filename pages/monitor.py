# pyrefly: ignore [missing-import]
from nicegui import ui
from components.layout import PageLayout, Panel, guard_page
from components.map_view import MapView, update_map
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
    with PageLayout('/monitor', 'Centro de monitoreo',
                    'Supervisión de búsquedas, cámaras y eventos pendientes de revisión.'):

        # ── Inject vibrant monitor-specific styles ──────────────────────
        ui.add_css("""
        .monitor-stat-strip {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
        }
        .monitor-stat-card {
            background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
            border: 1px solid rgba(0,240,255,0.12);
            border-radius: 14px;
            padding: 20px;
            position: relative;
            overflow: hidden;
            transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
        }
        .monitor-stat-card:hover {
            border-color: rgba(0,240,255,0.3);
            box-shadow: 0 8px 32px rgba(0,0,0,0.3), 0 0 20px rgba(0,240,255,0.08);
            transform: translateY(-2px);
        }
        .monitor-stat-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0;
            width: 100%; height: 3px;
            border-radius: 14px 14px 0 0;
        }
        .monitor-stat-card:nth-child(1)::before { background: linear-gradient(90deg, #00F0FF, #0088FF); }
        .monitor-stat-card:nth-child(2)::before { background: linear-gradient(90deg, #22D3EE, #06B6D4); }
        .monitor-stat-card:nth-child(3)::before { background: linear-gradient(90deg, #FFB800, #FF8C00); }
        .monitor-stat-card:nth-child(4)::before { background: linear-gradient(90deg, #FF3D71, #FF006E); }
        .monitor-stat-value {
            font-size: 32px;
            font-weight: 700;
            letter-spacing: -0.5px;
            line-height: 1;
        }
        .monitor-stat-card:nth-child(1) .monitor-stat-value { color: #00F0FF; text-shadow: 0 0 20px rgba(0,240,255,0.3); }
        .monitor-stat-card:nth-child(2) .monitor-stat-value { color: #22D3EE; text-shadow: 0 0 20px rgba(34,211,238,0.3); }
        .monitor-stat-card:nth-child(3) .monitor-stat-value { color: #FFB800; text-shadow: 0 0 20px rgba(255,184,0,0.3); }
        .monitor-stat-card:nth-child(4) .monitor-stat-value { color: #FF3D71; text-shadow: 0 0 20px rgba(255,61,113,0.3); }
        .monitor-stat-label {
            font-size: 13px;
            font-weight: 600;
            color: #E2E8F0;
            margin-top: 8px;
        }
        .monitor-stat-detail {
            font-size: 11px;
            color: #64748B;
            margin-top: 2px;
        }
        .monitor-map-header {
            background: linear-gradient(90deg, rgba(0,240,255,0.05), transparent);
            border-bottom: 1px solid rgba(0,240,255,0.1);
            padding: 10px 16px;
        }
        .monitor-map-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(0,240,255,0.08);
            border: 1px solid rgba(0,240,255,0.15);
            border-radius: 6px;
            padding: 3px 10px;
            font-size: 11px;
            font-weight: 600;
            color: #00F0FF;
            letter-spacing: 0.5px;
        }
        .monitor-map-badge::before {
            content: '';
            width: 6px; height: 6px;
            background: #00F0FF;
            border-radius: 50%;
            box-shadow: 0 0 6px rgba(0,240,255,0.6);
            animation: badge-pulse 2s ease-in-out infinite;
        }
        @keyframes badge-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }
        """)
        @ui.refreshable
        def stats():
            cases, cameras = get_active_cases(), get_cameras()
            pending = sum(m.status in ('Pendiente de validación', 'En revisión') for m in get_matches())
            alerts = sum(e.review_status in ('PENDIENTE_REVISION', 'EN_REVISION') for e in get_evidence())
            with ui.element('div').classes('monitor-stat-strip'):
                for value, label, detail in [
                    (len(cases), 'Casos activos', 'Búsquedas en curso'),
                    (f'{sum(c.status != "Desconectada" for c in cameras)}/{len(cameras)}',
                     'Cámaras conectadas', 'Red de demostración'),
                    (pending, 'Coincidencias pendientes', 'Requieren validación humana'),
                    (alerts, 'Evidencia por revisar', 'Posibles solicitudes de auxilio'),
                ]:
                    with ui.element('div').classes('monitor-stat-card'):
                        ui.label(str(value)).classes('monitor-stat-value')
                        ui.label(label).classes('monitor-stat-label')
                        ui.label(detail).classes('monitor-stat-detail')

        @ui.refreshable
        def camera_tiles():
            cameras = get_cameras()
            with ui.element('div').classes('camera-grid').style(
                    'grid-template-columns:repeat(3,minmax(0,1fr))'):
                for cid in ('CAM-003', 'CAM-007', 'CAM-008'):
                    CameraFeed(next(c for c in cameras if c.id == cid),
                               lambda camera_id: ui.navigate.to(f'/cameras?camera_id={camera_id}'))

        @ui.refreshable
        def side():
            cases = get_active_cases()
            with Panel('Actividad reciente', 'BITÁCORA'):
                ActivityLog(get_history(), 5)
                ui.link('Consultar historial completo →', '/history').classes(
                    'text-[11px] no-underline px-4 py-3 block border-t border-[#edf0f2]')
            with Panel('Casos activos', f'{len(cases)} EN BÚSQUEDA'):
                for case in cases:
                    with ui.link(target=f'/cases/{case.id}').classes('case-row no-underline text-inherit'):
                        ui.image(case.person.photos[0] if case.person.photos else '/assets/demo/person-1.svg').classes(
                            'case-thumb')
                        with ui.column().classes('gap-1'):
                            ui.label(case.person.name.replace(' (ficticia)', '').replace(' (ficticio)', '')).classes(
                                'text-xs font-medium')
                            ui.label(case.id).classes('mono muted')
                        ui.space()
                        ui.icon('chevron_right', size='15px', color='blue-grey-4')
            with ui.row().classes('page-note items-start'):
                ui.icon('info_outline', size='16px')
                ui.label('Datos y capturas ficticios. Las detecciones apoyan la revisión del operador.').classes(
                    'flex-1')

        def refresh():
            stats.refresh()
            camera_tiles.refresh()
            side.refresh()
            update_map(coverage)  # the map is not rebuilt: only its markers change

        stats()
        with ui.element('div').classes('workspace-grid mt-5'):
            with ui.column().classes('w-full gap-5 min-w-0'):
                with Panel('Cobertura de cámaras', 'MAPA INTERACTIVO · MAPBOX'):
                    with ui.row().classes('monitor-map-header items-center justify-between w-full'):
                        with ui.row().classes('items-center gap-3'):
                            ui.element('span').classes('monitor-map-badge').style('').props(
                                'innerHTML="ZONA MÉXICO"')
                            ui.label('Región Centro').classes('text-xs font-medium')
                        with ui.row().classes('gap-1'):
                            ui.button('Abrir seguimiento', icon='open_in_full',
                                      on_click=lambda: ui.navigate.to('/tracking')).props(
                                'flat dense no-caps size=sm')
                            ui.button(icon='refresh', on_click=refresh).props('flat dense').tooltip(
                                'Actualizar información')
                    coverage = MapView(get_cameras())
                with ui.row().classes('items-center justify-between w-full -mb-2'):
                    ui.label('Cámaras de interés').classes('section-title')
                    ui.link('Ver todas las cámaras →', '/cameras').classes('text-xs no-underline')
                camera_tiles()
            with ui.element('div').classes('stack'):
                side()
        ui.timer(15, refresh)
