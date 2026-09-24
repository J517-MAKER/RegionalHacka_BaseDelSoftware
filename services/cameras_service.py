from services import store


def get_cameras():
    return store.cameras


def get_camera(camera_id):
    return next((c for c in store.cameras if c.id == camera_id), None)


def get_nearby_cameras(camera_id, limit=3):
    origin = get_camera(camera_id)
    if not origin:
        return []
    return sorted((c for c in store.cameras if c.id!=camera_id), key=lambda c: (c.x-origin.x)**2+(c.y-origin.y)**2)[:limit]


def get_camera_events(camera_id):
    return [d for d in store.detections if d.camera_id == camera_id]
