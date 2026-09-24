from models.camera import Camera


def seed_cameras():
    names = ['Plaza central', 'Av. República', 'Entrada norte', 'Estación Alameda', 'Cruce Reforma',
             'Biblioteca', 'Pasillo central', 'Pasillo B', 'Mercado del Centro', 'Parque Norte',
             'Av. Universidad', 'Salida poniente', 'Cruce Hidalgo', 'Terminal sur', 'Acceso oriente', 'Plaza del Reloj']
    points = [(46,48),(24,26),(42,26),(69,20),(18,61),(65,47),(51,58),(74,65),
              (30,76),(47,12),(86,38),(38,64),(15,39),(62,82),(84,78),(59,33)]
    # Coordenadas reales en ciudades de México; CAM-008 (cámara del equipo) está en el Tec de Nuevo León.
    places = [(19.4326, -99.1332),   # Ciudad de México
              (29.0729, -110.9559),  # Hermosillo
              (28.6353, -106.0889),  # Chihuahua
              (25.6866, -100.3161),  # Monterrey
              (20.6597, -103.3496),  # Guadalajara
              (25.4232, -101.0053),  # Saltillo
              (21.8853, -102.2916),  # Aguascalientes
              (25.6775, -100.2597),  # Guadalupe, N. L. (Tec de Nuevo León)
              (19.7060, -101.1950),  # Morelia
              (31.6904, -106.4245),  # Ciudad Juárez
              (20.9674, -89.5926),   # Mérida
              (21.5042, -104.8946),  # Tepic
              (24.1426, -110.3128),  # La Paz
              (19.0414, -98.2063),   # Puebla
              (17.9892, -92.9475),   # Villahermosa
              (22.2331, -97.8611)]   # Tampico
    return [Camera(f'CAM-{i+1:03d}', name, name, 'Centro' if i<8 else 'Poniente',
                   'Desconectada' if i in (9,14) else 'Alerta' if i==7 else 'Posible coincidencia' if i in (2,6,11) else 'En línea',
                   *points[i], audio=i%3!=0,
                   last_seen='2026-09-23 09:12:00' if i in (9,14) else '2026-09-23 10:28:04',
                   lat=places[i][0], lng=places[i][1])
            for i,name in enumerate(names)]
