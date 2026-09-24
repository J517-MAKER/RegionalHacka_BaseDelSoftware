"""Geografía mínima para el seguimiento y la comparación con fichas.

Distancias reales entre cámaras (en km, sobre la superficie terrestre), la posición de cada
cámara en el mapa y la ubicación aproximada del «último lugar conocido» que declara una ficha.
Todo funciona sin conexión: no se consulta ningún servicio de geocodificación externo, así que
un lugar que no se reconoce simplemente queda sin situar (y no se inventa).
"""
import math
import re
import unicodedata

# Lugares frecuentes en fichas y ciudades donde hay cámaras de la red. (lat, lng)
GAZETTEER = {
    'tec de nuevo leon': (25.67750, -100.25970), 'tecnologico de nuevo leon': (25.67750, -100.25970),
    'macroplaza': (25.66930, -100.30970), 'fundidora': (25.67850, -100.28460),
    'plaza de la republica': (19.43610, -99.15450), 'monumento a la revolucion': (19.43610, -99.15450),
    'zocalo': (19.43260, -99.13320), 'plaza de la constitucion': (19.43260, -99.13320),
    'alameda central': (19.43560, -99.14370), 'bellas artes': (19.43520, -99.14120),
    'ciudad de mexico': (19.43260, -99.13320), 'cdmx': (19.43260, -99.13320),
    'monterrey': (25.68660, -100.31610), 'guadalupe': (25.67750, -100.25970),
    'san nicolas de los garza': (25.74170, -100.30220), 'san pedro garza garcia': (25.65820, -100.40260),
    'apodaca': (25.78140, -100.18830), 'escobedo': (25.79690, -100.32220), 'santa catarina': (25.67320, -100.45810),
    'guadalajara': (20.65970, -103.34960), 'zapopan': (20.72360, -103.38480), 'puebla': (19.04140, -98.20630),
    'tijuana': (32.51490, -117.03820), 'mexicali': (32.62450, -115.45230), 'leon': (21.12200, -101.68200),
    'queretaro': (20.58880, -100.38990), 'merida': (20.96740, -89.59260), 'cancun': (21.16190, -86.85150),
    'toluca': (19.28260, -99.65570), 'chihuahua': (28.63530, -106.08890), 'hermosillo': (29.07290, -110.95590),
    'saltillo': (25.42320, -101.00530), 'aguascalientes': (21.88530, -102.29160), 'morelia': (19.70600, -101.19500),
    'ciudad juarez': (31.69040, -106.42450), 'tepic': (21.50420, -104.89460), 'la paz': (24.14260, -110.31280),
    'villahermosa': (17.98920, -92.94750), 'tampico': (22.23310, -97.86110), 'veracruz': (19.17380, -96.13420),
    'xalapa': (19.54380, -96.91020), 'oaxaca': (17.07320, -96.72660), 'acapulco': (16.85310, -99.82370),
    'culiacan': (24.80910, -107.39400), 'mazatlan': (23.24940, -106.41110), 'durango': (24.02770, -104.65320),
    'san luis potosi': (22.15650, -100.98550), 'torreon': (25.54280, -103.40680), 'zacatecas': (22.77090, -102.58320),
    'tuxtla gutierrez': (16.75280, -93.11670), 'campeche': (19.83010, -90.53490), 'chetumal': (18.50360, -88.30550),
    'colima': (19.24520, -103.72410), 'pachuca': (20.10110, -98.75910), 'cuernavaca': (18.92420, -99.22160),
    'tlaxcala': (19.31810, -98.23750), 'reynosa': (26.09230, -98.27770), 'matamoros': (25.86970, -97.50270),
    'nuevo laredo': (27.47790, -99.51550), 'ensenada': (31.86670, -116.59640),
}


def plain(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', (text or '').lower()) if unicodedata.category(c) != 'Mn')
    return ' '.join(re.sub(r'[^a-z0-9\s]', ' ', text).split())


def haversine_km(a, b):
    """Distancia en km entre dos (lat, lng)."""
    (lat1, lng1), (lat2, lng2) = a, b
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(h)))


def bearing(a, b):
    """Rumbo en grados (0 = norte, 90 = este) de a hacia b."""
    (lat1, lng1), (lat2, lng2) = a, b
    phi1, phi2, dlmb = math.radians(lat1), math.radians(lat2), math.radians(lng2 - lng1)
    y = math.sin(dlmb) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlmb)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def camera_position(camera):
    """(lat, lng) de una cámara; las que sólo tienen posición en el plano se proyectan sobre México."""
    if camera is None:
        return None
    if getattr(camera, 'lat', None) is not None and getattr(camera, 'lng', None) is not None:
        return float(camera.lat), float(camera.lng)
    return 32.718655 - (camera.y / 100.0) * 18.186557, -118.407986 + (camera.x / 100.0) * 31.697581


def human_distance(km):
    if km is None:
        return '—'
    return f'{km * 1000:.0f} m' if km < 1 else f'{km:.1f} km' if km < 20 else f'{km:.0f} km'


def resolve_place(text):
    """(lat, lng, etiqueta) del lugar que declara una ficha, o None si no se reconoce.

    Primero una cámara de la red cuyo nombre aparezca en el texto (el lugar exacto); si no,
    el lugar o la ciudad más específica del catálogo local.
    """
    needle = plain(text)
    if not needle:
        return None
    from services.cameras_service import get_cameras
    for camera in get_cameras():
        name = plain(camera.name)
        if name and (name in needle or needle in name):
            lat, lng = camera_position(camera)
            return lat, lng, f'{camera.id} · {camera.name}'
    best = None
    for place, (lat, lng) in GAZETTEER.items():
        if re.search(r'\b' + re.escape(place) + r'\b', needle) and (best is None or len(place) > len(best[0])):
            best = (place, lat, lng)
    if best:
        return best[1], best[2], best[0].title()
    return None


def nearest_cameras(position, cameras, limit=3, exclude=()):
    """Cámaras más cercanas a una posición, con su distancia en km."""
    ranked = sorted(((haversine_km(position, camera_position(c)), c) for c in cameras if c.id not in exclude),
                    key=lambda item: item[0])
    return ranked[:limit]
