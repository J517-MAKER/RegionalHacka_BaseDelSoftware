from models.camera import Camera

NAMES = ['Plaza central', 'Av. República', 'Entrada norte', 'Estación Alameda', 'Cruce Reforma',
         'Biblioteca', 'Pasillo central', 'Pasillo B', 'Mercado del Centro', 'Parque Norte',
         'Av. Universidad', 'Salida poniente', 'Cruce Hidalgo', 'Terminal sur', 'Acceso oriente', 'Plaza del Reloj']
POINTS = [(46,48),(24,26),(42,26),(69,20),(18,61),(65,47),(51,58),(74,65),
          (30,76),(47,12),(86,38),(38,64),(15,39),(62,82),(84,78),(59,33)]


def seed_cameras():
    import config
    cameras = [Camera(f'CAM-{i+1:03d}', name, name, 'Centro' if i<8 else 'Poniente',
                      'Desconectada' if i in (9,14) else 'Alerta' if i==7 else 'Posible coincidencia' if i in (2,6,11) else 'En línea',
                      *POINTS[i], audio=i%3!=0,
                      last_seen='2026-09-23 09:12:00' if i in (9,14) else '2026-09-23 10:28:04')
               for i,name in enumerate(NAMES)]
    for camera in cameras:
        # Topología explícita: qué cámaras son contiguas. Permite evaluar si una secuencia
        # de detecciones es geográficamente coherente sin inventar el camino recorrido.
        camera.nearby_camera_ids = [c.id for c in sorted(
            (c for c in cameras if c.id != camera.id),
            key=lambda c: (c.x-camera.x)**2 + (c.y-camera.y)**2)[:3]]
        # La cámara asociada al equipo usa su webcam; el resto son fuentes simuladas.
        camera.stream_source = 'webcam' if camera.id == config.DEFAULT_CAMERA_ID else 'simulated'
        camera.stream_status = 'CAMERA_STREAM_OFFLINE' if camera.status == 'Desconectada' else 'CAMERA_STREAM_ACTIVE'
    return cameras
