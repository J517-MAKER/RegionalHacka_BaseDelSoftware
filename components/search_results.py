"""Resultados de búsqueda de un caso: candidatos, última validada y última posible.

La última detección validada y la última posible se muestran por separado y nunca se
mezclan: una la confirmó un supervisor como relevante para la investigación, la otra
todavía no la ha visto nadie.
"""
from nicegui import ui
from components.layout import Panel, notify_action
from components.person_profile import InfoPair
from services.search_matching_service import (get_candidates, get_profile, last_locations,
                                              run_search)
from services.users_service import can


def SearchResults(case_id):
    @ui.refreshable
    def results():
        profile = get_profile(case_id)
        candidates = get_candidates(case_id)
        pending = [c for c in candidates if c.status in ('AI_CANDIDATE', 'PENDING_HUMAN_REVIEW')]
        escalated = [c for c in candidates if c.status == 'OPERATOR_ACCEPTED_FOR_REVIEW']
        validated = [c for c in candidates if c.status == 'SUPERVISOR_VALIDATED']
        rejected = [c for c in candidates if c.status in ('OPERATOR_REJECTED', 'SUPERVISOR_REJECTED')]
        last = last_locations(case_id)

        with Panel('Resultados de búsqueda', 'PRIORIZACIÓN · IDENTIDAD NO CONFIRMADA'):
            with ui.column().classes('panel-body gap-2'):
                if not profile:
                    ui.label('Este caso todavía no tiene un perfil de búsqueda. Se crea al importar '
                             'una ficha y confirmar su fotografía y sus datos.').classes('text-xs muted')
                else:
                    InfoPair('Estado de la búsqueda', profile.search_status)
                    InfoPair('Referencia facial', profile.face_status)
                    if profile.disappearance_datetime:
                        InfoPair('Ventana prioritaria desde', profile.disappearance_datetime
                                 + ('' if profile.disappearance_time_known else ' (hora no declarada)'))
                for label, items in [('Candidatos pendientes', pending),
                                     ('Enviados a supervisión', escalated),
                                     ('Coincidencias validadas', validated),
                                     ('Coincidencias rechazadas', rejected)]:
                    InfoPair(label, str(len(items)))

                # Las dos últimas ubicaciones no se mezclan: significan cosas distintas.
                ui.label('ÚLTIMA DETECCIÓN VALIDADA').classes('eyebrow mt-2')
                if last['validated']:
                    ui.label(f'{last["validated"].camera_id} · {last["validated"].timestamp}').classes('text-sm')
                else:
                    ui.label('Sin detecciones validadas por supervisión.').classes('text-xs muted')
                ui.label('ÚLTIMA DETECCIÓN POSIBLE').classes('eyebrow mt-2')
                if last['possible']:
                    ui.label(f'{last["possible"].camera_id} · {last["possible"].timestamp} · '
                             'pendiente de revisión').classes('text-sm')
                else:
                    ui.label('Sin detecciones posibles pendientes.').classes('text-xs muted')

                with ui.row().classes('gap-2 mt-3 flex-wrap'):
                    if profile and can('cases.manage'):
                        ui.button('INICIAR BÚSQUEDA', icon='travel_explore',
                                  on_click=lambda: notify_action(
                                      lambda: run_search(case_id),
                                      'Búsqueda ejecutada sobre las detecciones almacenadas.',
                                      results.refresh)).props('unelevated no-caps')
                    if candidates:
                        ui.button('Revisar candidatos', icon='compare',
                                  on_click=lambda: ui.navigate.to(f'/matches?case_id={case_id}')
                                  ).props('outline no-caps')
                    ui.button('Ver trayectoria', icon='route',
                              on_click=lambda: ui.navigate.to(f'/tracking?case_id={case_id}')
                              ).props('flat no-caps')
                ui.label('La búsqueda compara también detecciones anteriores al registro de la ficha. '
                         'Los resultados son internos y requieren revisión humana.').classes('text-xs muted')
    results()
    return results
