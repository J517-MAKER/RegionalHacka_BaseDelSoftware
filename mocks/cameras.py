from models.camera import Camera


def seed_cameras():
    names = ['Plaza central', 'Av. República', 'Entrada norte', 'Estación Alameda', 'Cruce Reforma',
             'Biblioteca', 'Pasillo central', 'Pasillo B', 'Mercado del Centro', 'Parque Norte',
             'Av. Universidad', 'Salida poniente', 'Cruce Hidalgo', 'Terminal sur', 'Acceso oriente', 'Plaza del Reloj']
    points = [(46,48),(24,26),(42,26),(69,20),(18,61),(65,47),(51,58),(74,65),
              (30,76),(47,12),(86,38),(38,64),(15,39),(62,82),(84,78),(59,33)]
    return [Camera(f'CAM-{i+1:03d}', name, name, 'Centro' if i<8 else 'Poniente',
                   'Desconectada' if i in (9,14) else 'Alerta' if i==7 else 'Posible coincidencia' if i in (2,6,11) else 'En línea',
                   *points[i], audio=i%3!=0,
                   last_seen='2026-09-23 09:12:00' if i in (9,14) else '2026-09-23 10:28:04')
            for i,name in enumerate(names)]
