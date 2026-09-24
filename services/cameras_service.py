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
