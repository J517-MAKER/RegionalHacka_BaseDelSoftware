from services import store


def get_cameras():
    return store.cameras


def get_camera(camera_id):
    return next((c for c in store.cameras if c.id == camera_id), None)


def get_nearby_cameras(camera_id, limit=3):
    """Las cámaras más cercanas por distancia real, igual que las que une el mapa."""
    from services.geo_service import camera_position, haversine_km
    origin = get_camera(camera_id)
    if not origin:
        return []
    here = camera_position(origin)
    return sorted((c for c in store.cameras if c.id != camera_id),
                  key=lambda c: haversine_km(here, camera_position(c)))[:limit]


def get_camera_events(camera_id):
    return [d for d in store.detections if d.camera_id == camera_id]


# ------------------------------------------------- la escucha y la evidencia de una cámara
# El micrófono no es un módulo aparte: pertenece a la cámara. Estas funciones responden, para
# una cámara concreta, qué está oyendo y qué se conservó cuando oyó una petición de auxilio.

def audio_analyzed(camera_id):
    """True cuando el monitoreo continuo analiza el audio de esta cámara."""
    from services.camera_monitor_service import monitor
    return monitor.audio_session().camera_id == camera_id


def camera_listening_state(camera_id):
    """Estado de la escucha de esta cámara, para contarlo dentro de su propia vista."""
    from services.camera_monitor_service import monitor
    camera = get_camera(camera_id)
    if not audio_analyzed(camera_id):
        return {'analyzed': False, 'listening': False, 'state': 'SIN ESCUCHA', 'level': 0.0,
                'detail': 'El micrófono de esta cámara no se analiza en este equipo.' if camera and camera.audio
                else 'Esta cámara no entrega audio.'}
    session = monitor.audio_session()
    audio = monitor.audio_state()
    return {'analyzed': True, 'listening': session.running,
            'state': session.status if session.running else audio['state'],
            'level': session.level if session.running else 0.0,
            'detail': audio['detail'] or 'Escucha continua desde que arranca NEXO.'}


def last_analysis(camera_id):
    """Último análisis de voz de esta cámara, tal como lo ve el operador. None si no hay."""
    from services.camera_monitor_service import monitor
    if not audio_analyzed(camera_id):
        return None
    return next((r for r in monitor.audio_session().results if r['camera'] == camera_id), None)


def get_camera_evidence(camera_id, limit=None):
    """Eventos de auxilio en los que participó esta cámara, por micrófono o por imagen.

    Cuando la cámara del micrófono no transmitía, el clip salió de otra cámara del equipo: esa
    otra cámara también debe mostrar el evento, porque su video es parte de la evidencia.
    """
    events = [e for e in store.evidence
              if camera_id in (e.camera_id, e.video_camera_id)
              or any(v.get('camera_id') == camera_id for v in e.extra_videos)]
    return events[:limit] if limit else events


def recent_camera_evidence(camera_id, within_seconds=None):
    """La evidencia más reciente de esta cámara si acaba de crearse; si no, None.

    Sirve para que la propia cámara anuncie que conservó el fragmento, sin que nadie tenga que
    ir a buscarlo a otra pantalla.
    """
    from datetime import datetime
    import config
    window = config.CAMERA_EVENT_NOTICE_SECONDS if within_seconds is None else within_seconds
    for event in get_camera_evidence(camera_id):
        try:
            created = datetime.strptime(event.created_at, '%Y-%m-%d %H:%M:%S')
        except (TypeError, ValueError):
            continue
        if 0 <= (datetime.now() - created).total_seconds() <= window:
            return event
    return None


def evidence_summary(event):
    """Qué quedó guardado de un evento, en una línea: imagen + audio + video."""
    from services.event_frames_service import get_event_frames
    photos = sum(1 for f in get_event_frames(event.event_id) if f.image_path)
    parts = []
    if event.video_status == 'ATTACHED' and event.video_file:
        parts.append('video con audio' if event.video_has_audio else 'video')
    if event.audio_file:
        parts.append(f'audio {event.audio_duration:.0f} s')
    if photos:
        parts.append(f'{photos} foto(s)')
    return ' · '.join(parts) or 'sin archivos conservados'
