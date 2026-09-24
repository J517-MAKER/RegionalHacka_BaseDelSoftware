"""Adapters to replace when vision and tracking are available."""


def request_person_detection(camera_id: str, alert_id: str):
    """Real when live recognition is running on that camera; pending otherwise."""
    from services.live_recognition_service import running_for_camera
    inst = running_for_camera(camera_id)
    faces = inst.snapshot_faces(camera_id) if inst else []
    if inst:
        return {'success': True, 'mock': False, 'status': 'VISION_ACTIVE', 'camera_id': camera_id,
                'alert_id': alert_id, 'faces': faces}
    return {'success': True, 'mock': True, 'status': 'WAITING_FOR_VISION_MODULE',
            'camera_id': camera_id, 'alert_id': alert_id}


def start_tracking_from_alert(alert_id: str, camera_id: str):
    return {'success': True, 'mock': True, 'status': 'WAITING_FOR_TRACKING_MODULE',
            'camera_id': camera_id, 'alert_id': alert_id,
            'vision': request_person_detection(camera_id, alert_id)}
