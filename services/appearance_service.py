"""Rasgos visibles que una ficha declara y una cámara puede estimar, para compararlos.

Sólo se estima lo observable y útil para priorizar la revisión: el color predominante de la
ropa superior (la ficha suele decir «chamarra azul») y la edad aproximada que da el modelo
facial. No se infieren atributos sensibles (tono de piel, sexo, origen): la ficha los declara,
pero una imagen no debe decidirlos. Ningún rasgo descarta a nadie; la ropa pudo cambiar y la
edad estimada puede fallar varios años.
"""
import re
import unicodedata

# Nombres de color tal como aparecen en fichas, agrupados en familias comparables.
COLOR_WORDS = {
    'negro': 'negro', 'negra': 'negro', 'oscuro': 'negro', 'oscura': 'negro',
    'blanco': 'blanco', 'blanca': 'blanco', 'crema': 'blanco', 'beige': 'blanco', 'hueso': 'blanco',
    'gris': 'gris', 'plata': 'gris', 'plateado': 'gris',
    'rojo': 'rojo', 'roja': 'rojo', 'guinda': 'rojo', 'vino': 'rojo', 'tinto': 'rojo',
    'rosa': 'rosa', 'rosado': 'rosa', 'rosada': 'rosa', 'fucsia': 'rosa',
    'naranja': 'naranja', 'anaranjado': 'naranja', 'anaranjada': 'naranja', 'coral': 'naranja',
    'amarillo': 'amarillo', 'amarilla': 'amarillo', 'mostaza': 'amarillo', 'dorado': 'amarillo',
    'verde': 'verde', 'olivo': 'verde', 'militar': 'verde', 'menta': 'verde',
    'azul': 'azul', 'marino': 'azul', 'celeste': 'azul', 'turquesa': 'azul', 'mezclilla': 'azul',
    'morado': 'morado', 'morada': 'morado', 'lila': 'morado', 'violeta': 'morado', 'purpura': 'morado',
    'cafe': 'cafe', 'marron': 'cafe', 'chocolate': 'cafe', 'caqui': 'cafe', 'kaki': 'cafe', 'camel': 'cafe',
}
COLOR_LABELS = {'negro': 'negro', 'blanco': 'blanco', 'gris': 'gris', 'rojo': 'rojo', 'rosa': 'rosa',
                'naranja': 'naranja', 'amarillo': 'amarillo', 'verde': 'verde', 'azul': 'azul',
                'morado': 'morado', 'cafe': 'café'}
# Colores que se confunden con facilidad en cámaras con poca luz o balance de blancos pobre.
NEIGHBOURS = {('negro', 'gris'), ('gris', 'blanco'), ('azul', 'morado'), ('rojo', 'rosa'),
              ('naranja', 'cafe'), ('rojo', 'cafe'), ('amarillo', 'naranja'), ('verde', 'azul')}
# Prendas superiores: si la ficha las menciona, su color es el que se compara con el torso.
UPPER_GARMENTS = ('playera', 'camisa', 'camiseta', 'blusa', 'sudadera', 'chamarra', 'chaqueta', 'sueter',
                  'saco', 'chaleco', 'abrigo', 'top', 'jersey', 'polo', 'uniforme', 'vestido', 'hoodie',
                  'rompevientos', 'gabardina')
# Prendas y accesorios que no se ven en el torso: su color no se compara con él.
OTHER_GARMENTS = ('pantalon', 'pantalones', 'jeans', 'short', 'shorts', 'falda', 'calzado', 'zapatos', 'zapato',
                  'tenis', 'botas', 'bota', 'sandalias', 'huaraches', 'calcetas', 'mallas', 'bermuda', 'bermudas',
                  'leggins', 'gorra', 'sombrero', 'mochila', 'bolsa', 'lentes', 'cinturon')


def _plain(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', (text or '').lower()) if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9\s]', ' ', text)


def declared_colors(text, upper_only=True):
    """Familias de color que menciona una ficha. Con `upper_only`, primero las de la ropa
    superior («chamarra azul, pantalón negro» -> {'azul'}); si no distingue prendas, todas."""
    words = _plain(text).split()
    everything, upper = [], []
    for index, word in enumerate(words):
        family = COLOR_WORDS.get(word)
        if not family:
            continue
        everything.append(family)
        # La prenda a la que se refiere el color es la más cercana antes de él
        # («chaqueta azul, pantalón oscuro»: el oscuro es del pantalón).
        garment = next((w for w in reversed(words[max(0, index - 3):index])
                        if w in UPPER_GARMENTS or w in OTHER_GARMENTS), None)
        if garment in UPPER_GARMENTS:
            upper.append(family)
    chosen = upper if upper_only and upper else everything
    return list(dict.fromkeys(chosen))


def dominant_color(pixels):
    """Familia de color predominante de una región BGR, o None si no hay suficiente imagen."""
    import cv2
    import numpy as np
    if pixels is None or pixels.size == 0 or min(pixels.shape[:2]) < 12:
        return None
    hsv = cv2.cvtColor(pixels, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype('int32')
    hue, sat, val = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    families = np.full(hue.shape, '', dtype=object)
    dark, light, grey = val < 50, (sat < 35) & (val > 190), sat < 45
    families[dark] = 'negro'
    families[~dark & light] = 'blanco'
    families[~dark & ~light & grey] = 'gris'
    chroma = ~dark & ~grey
    # OpenCV usa matiz de 0 a 179.
    for family, low, high in (('rojo', 0, 7), ('naranja', 8, 19), ('amarillo', 20, 33), ('verde', 34, 85),
                              ('azul', 86, 128), ('morado', 129, 150), ('rosa', 151, 169), ('rojo', 170, 179)):
        families[chroma & (hue >= low) & (hue <= high)] = family
    # Un naranja apagado y oscuro se ve café en la ropa.
    families[chroma & (hue >= 5) & (hue <= 22) & (val < 140)] = 'cafe'
    values, counts = np.unique(families[families != ''], return_counts=True)
    if not len(values):
        return None
    best = int(np.argmax(counts))
    return values[best] if counts[best] / max(1, len(hue)) >= .25 else None


def upper_clothing_color(frame, bbox):
    """Color predominante del torso, justo debajo del rostro; None si el torso no se ve."""
    try:
        x1, y1, x2, y2 = (int(v) for v in bbox)
        width, height = x2 - x1, y2 - y1
        if width <= 0 or height <= 0 or frame is None:
            return None
        rows, cols = frame.shape[:2]
        top, bottom = y2 + int(height * .35), y2 + int(height * 1.6)
        left, right = x1 - int(width * .25), x2 + int(width * .25)
        top, bottom = max(0, top), min(rows, bottom)
        left, right = max(0, left), min(cols, right)
        if bottom - top < max(12, height * .4) or right - left < 12:
            return None  # el cuadro corta a la persona a la altura del cuello
        family = dominant_color(frame[top:bottom, left:right])
        return COLOR_LABELS.get(family) if family else None
    except Exception:
        return None


def _family(label):
    plain = _plain(label).strip()
    return COLOR_WORDS.get(plain, plain)


def clothing_compatibility(declared_text, observed):
    """(nivel, detalle) al comparar la vestimenta declarada con el color observado."""
    colors = declared_colors(declared_text)
    if not colors:
        return 'NO_EVALUABLE', 'La ficha no menciona colores de vestimenta.'
    if not observed:
        return 'NO_EVALUABLE', 'La cámara no captó la ropa superior con claridad.'
    seen = _family(observed)
    names = ', '.join(COLOR_LABELS.get(c, c) for c in colors)
    if seen in colors:
        return 'MEDIA', f'Ropa superior {observed}: coincide con lo declarado ({names}).'
    if any((seen, c) in NEIGHBOURS or (c, seen) in NEIGHBOURS for c in colors):
        return 'BAJA', f'Ropa superior {observed}: cercano a lo declarado ({names}); la luz puede confundirlos.'
    return 'BAJA', (f'Ropa superior {observed}; la ficha declara {names}. No descarta: la ropa pudo '
                    'cambiar desde la desaparición.')


def declared_age(text):
    match = re.search(r'\d{1,3}', str(text or ''))
    age = int(match[0]) if match else None
    return age if age is not None and 0 < age < 120 else None


def age_compatibility(declared, estimated, years_elapsed=0.0):
    """(nivel, detalle): la edad estimada por el modelo contra la declarada en la ficha."""
    age = declared_age(declared)
    if age is None:
        return 'NO_EVALUABLE', 'La ficha no declara una edad comparable.'
    if estimated is None:
        return 'NO_EVALUABLE', 'No hay una estimación de edad de la captura.'
    expected = age + max(0.0, years_elapsed)
    gap = abs(float(estimated) - expected)
    if gap <= 6:
        return 'MEDIA', f'Edad aparente ~{estimated} años; la ficha declara {age}. Compatible.'
    if gap <= 12:
        return 'BAJA', f'Edad aparente ~{estimated} años frente a {age} declarados: diferencia moderada.'
    return 'BAJA', (f'Edad aparente ~{estimated} años frente a {age} declarados. La estimación puede '
                    'fallar varios años; no descarta.')
