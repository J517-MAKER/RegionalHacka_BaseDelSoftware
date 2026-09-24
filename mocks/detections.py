from models.detection import Detection
from models.match import Match


def seed_detections():
    detections = [Detection(f'DET-{i+1:03d}', 'BUS-2026-0184', camera, f'2026-09-23 {time}', score)
                  for i,(camera,time,score) in enumerate([('CAM-003','10:21:14',91),('CAM-007','10:23:02',88),('CAM-012','10:25:41',93)])]
    detections += [Detection(f'DET-{i+4:03d}', f'BUS-2026-{185+i%3:04d}', f'CAM-{i+1:03d}',
                            f'2026-09-23 09:{12+i*4:02d}:18', 76+i*2,
                            capture=f'/assets/demo/person-{2+i%3}.svg') for i in range(7)]
    return detections


def seed_matches():
    return [Match(f'MAT-{i+1:03d}', f'DET-{i+1:03d}') for i in range(6)]
