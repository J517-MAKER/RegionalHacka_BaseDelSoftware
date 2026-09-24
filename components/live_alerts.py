"""Avisos en vivo en el encabezado de todas las páginas.

Un evento de auxilio o una posible coincidencia con una ficha no puede depender de que alguien
tenga abierta la página correcta: el encabezado cuenta lo pendiente, avisa en cuanto llega algo
nuevo y lleva directo a revisarlo. Los avisos dicen niveles, nunca porcentajes: todavía nadie
ha revisado lo que se anuncia.
"""
from nicegui import ui
from services import store
from services.users_service import can

REFRESH_SECONDS = 2


def _set_href(link, url):
    if link.props.get('href') != url:
        link.props['href'] = url
        link.update()


def SetupNotice():
    """Mientras los modelos facial y de voz se preparan (la primera vez, descargándose solos),
    el encabezado lo dice; si falló la descarga, que se reintenta sola. Listos, desaparece."""
    from services.model_setup import WORKING, setup
    chip = ui.element('div').classes('header-alert-chip setup').mark('header-setup')
    with chip:
        spinner = ui.spinner(size='11px')
        problem = ui.icon('sync_problem', size='13px')
        text = ui.label('')
        tip = ui.tooltip('')

    def refresh():
        notice = setup.notice()
        chip.set_visibility(bool(notice))
        if not notice:
            return
        working = setup.face in WORKING or setup.voice in WORKING
        spinner.set_visibility(working)
        problem.set_visibility(not working)
        if working:
            chip.classes(remove='failed')
        else:
            chip.classes(add='failed')
        text.set_text(notice[0])
        tip.set_text(notice[1])

    refresh()
    ui.timer(REFRESH_SECONDS, refresh)


def HeaderAlerts():
    show_events, show_matches = can('alerts.view'), can('matches.view')
    SetupNotice()
    if not (show_events or show_matches):
        return
    # Lo que ya existía al abrir la página no se anuncia otra vez: sólo lo nuevo.
    seen = {'events': {e.event_id for e in store.evidence},
            'matches': {c.candidate_match_id for c in store.candidate_matches},
            'sightings': {s.sighting_id for s in store.track_sightings}}

    distress = ui.link(target='/alerts?status=PENDIENTE_REVISION').classes('header-alert-chip distress') \
        .mark('header-distress')
    with distress:
        ui.element('span').classes('status-dot')
        distress_text = ui.label('')
    matches = ui.link(target='/matches').classes('header-alert-chip matches').mark('header-matches')
    with matches:
        ui.element('span').classes('status-dot')
        matches_text = ui.label('')

    def refresh():
        pending = [e for e in store.evidence if e.review_status == 'PENDIENTE_REVISION'] if show_events else []
        distress.set_visibility(bool(pending))
        if pending:
            distress_text.set_text(f'{len(pending)} EVENTO{"S" if len(pending) != 1 else ""} DE AUXILIO SIN REVISAR')
            _set_href(distress, f'/alerts?event_id={pending[0].event_id}' if len(pending) == 1
                      else '/alerts?status=PENDIENTE_REVISION')
        candidates = [c for c in store.candidate_matches
                      if c.status in ('AI_CANDIDATE', 'PENDING_HUMAN_REVIEW')] if show_matches else []
        matches.set_visibility(bool(candidates))
        if candidates:
            matches_text.set_text(f'{len(candidates)} COINCIDENCIA{"S" if len(candidates) != 1 else ""} '
                                  'CON FICHAS POR REVISAR')

        for event in [e for e in store.evidence if e.event_id not in seen['events']] if show_events else []:
            seen['events'].add(event.event_id)
            video = ('con video, audio y fotos' if event.video_status == 'ATTACHED' else 'con audio')
            ui.notify(f'Posible solicitud de auxilio en {event.camera_id} · {event.location}. '
                      f'Evidencia {video} lista para revisión ({event.event_id}).',
                      type='negative', position='top', timeout=12000, close_button='Cerrar', multi_line=True)
        for candidate in [c for c in store.candidate_matches if c.candidate_match_id not in seen['matches']] \
                if show_matches else []:
            seen['matches'].add(candidate.candidate_match_id)
            if candidate.status not in ('AI_CANDIDATE', 'PENDING_HUMAN_REVIEW') or not candidate.linked_to_distress_event:
                continue  # las búsquedas manuales ya se ven en su propia página
            ui.notify(f'Una persona del evento {candidate.event_id} se parece a la ficha {candidate.case_id} '
                      f'(rostro {candidate.signal("face").level}). Pendiente de revisión humana.',
                      type='warning', position='top', timeout=10000, close_button='Cerrar', multi_line=True)
        for sighting in [s for s in store.track_sightings if s.sighting_id not in seen['sightings']] \
                if show_events else []:
            seen['sightings'].add(sighting.sighting_id)
            ui.notify(f'{sighting.track_id} del evento {sighting.event_id} reapareció en {sighting.camera_id}. '
                      'El trayecto se actualizó en Mapa y seguimiento.',
                      type='info', position='top', timeout=8000, close_button='Cerrar', multi_line=True)

    refresh()
    ui.timer(REFRESH_SECONDS, refresh)
