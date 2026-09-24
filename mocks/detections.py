from models.detection import Detection
from models.match import Match

# Detecciones de demostración con trayectos posibles en el tiempo transcurrido: el mapa las une
# y un salto imposible (cientos de km en minutos) delataría datos incoherentes.
# BUS-2026-0184 camina entre las tres cámaras del equipo (celular -> USB -> laptop), a pocos
# metros entre sí; los demás casos se mueven entre ciudades a lo largo de días.
SEEDS = [
    ('BUS-2026-0184', 'CAM-004', '2026-09-23 10:21:14', 91),
    ('BUS-2026-0184', 'CAM-007', '2026-09-23 10:23:02', 88),
    ('BUS-2026-0184', 'CAM-008', '2026-09-23 10:25:41', 93),
    ('BUS-2026-0185', 'CAM-001', '2026-09-21 18:40:18', 76),
    ('BUS-2026-0186', 'CAM-009', '2026-09-20 21:16:18', 78),
    ('BUS-2026-0187', 'CAM-003', '2026-09-21 09:20:18', 80),
    ('BUS-2026-0185', 'CAM-014', '2026-09-22 08:24:18', 82),
    ('BUS-2026-0186', 'CAM-005', '2026-09-22 09:28:18', 84),
    ('BUS-2026-0187', 'CAM-006', '2026-09-23 09:32:18', 86),
    ('BUS-2026-0185', 'CAM-016', '2026-09-23 09:36:18', 88),
]


def seed_detections():
    detections = []
    for i, (case_id, camera, when, score) in enumerate(SEEDS):
        capture = '/assets/demo/capture.svg' if i < 3 else f'/assets/demo/person-{2 + (i - 3) % 3}.svg'
        detections.append(Detection(f'DET-{i + 1:03d}', case_id, camera, when, score, capture=capture))
    return detections


def seed_matches():
    return [Match(f'MAT-{i+1:03d}', f'DET-{i+1:03d}') for i in range(6)]
