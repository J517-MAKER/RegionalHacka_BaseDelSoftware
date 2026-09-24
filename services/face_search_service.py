"""Búsqueda por ficha: una imagen de referencia contra todo lo que las cámaras guardaron.

La referencia puede ser una ficha de búsqueda (se lee con OCR y se recorta la fotografía) o una
fotografía autorizada (por ejemplo, la que entrega la familia). De ella se obtienen los rasgos
que se comparan: la huella del rostro y la edad aparente; lo demás lo declara la persona que
consulta. Consultar no crea candidatos: un operador decide qué resultado se envía a revisión.
"""
import base64
from datetime import datetime
from uuid import uuid4
import config
from services import face_engine, store


class ReferenceError_(ValueError):
    """La imagen no sirve como referencia; el mensaje es para quien consulta."""


def model_status():
    """(listo, mensaje) del motor facial en este equipo, sin descargar nada."""
    if not face_engine.installed():
        return False, 'InsightFace no está instalado: python -m pip install -r requirements.txt'
    if face_engine.ready():
        return True, 'Motor facial listo.'
    from services.model_setup import setup
    if setup.face == 'DESCARGANDO':
        downloaded = face_engine.download_progress()
        return False, ('Descargando el modelo facial por primera vez (unos 280 MB)'
                       + (f': {downloaded:.0f} MB' if downloaded else '') + '. La búsqueda se habilita sola al terminar.')
    if setup.face == 'ERROR':
        return False, f'{setup.face_error} También puedes reintentarlo aquí.'
    return False, ('El modelo facial no está descargado en este equipo (descarga única de unos 280 MB). '
                   'Puedes descargarlo aquí.')


def download_model():
    """Descarga y carga el modelo facial. Tarda unos minutos la primera vez."""
    face_engine.load(download=True)
    return True


def save_reference_image(content, content_type=''):
    """Guarda la imagen subida con un nombre generado (el nombre original no se usa)."""
    from services.alert_import_service import detect_type, ensure_directories
    if not content:
        raise ReferenceError_('El archivo está vacío.')
    if len(content) > config.IMPORT_MAX_BYTES:
        raise ReferenceError_('El archivo supera el límite de 10 MB.')
    kind = detect_type(content, content_type)
    if kind == 'application/pdf':
        raise ReferenceError_('Para un PDF usa la opción «Ficha de búsqueda»: se lee con OCR y se recorta la foto.')
    ensure_directories()
    suffix = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}[kind]
    path = config.IMPORT_PHOTOS_DIR / ('REF-' + datetime.now().strftime('%Y%m%d') + '-' + uuid4().hex[:6].upper() + suffix)
    path.write_bytes(content)
    return path


def face_reference(image):
    """Rostro más visible de la imagen: huella, edad aparente y recorte para mostrarlo."""
    import cv2
    pixels = face_engine.read_image(image)
    if pixels is None:
        raise ReferenceError_('No fue posible leer la imagen.')
    faces = face_engine.analyze(pixels)
    if not faces:
        raise ReferenceError_('No se detectó un rostro en la imagen. Usa una fotografía de frente y bien iluminada.')
    face = faces[0]
    x1, y1, x2, y2 = face.bbox
    margin = int(max(x2 - x1, y2 - y1) * .45)
    height, width = pixels.shape[:2]
    crop = pixels[max(0, y1 - margin):min(height, y2 + margin), max(0, x1 - margin):min(width, x2 + margin)]
    data = cv2.imencode('.jpg', crop, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()
    return {'embedding': [float(v) for v in face.embedding], 'age': face.age, 'det_score': round(face.det_score, 3),
            'faces': len(faces), 'crop': 'data:image/jpeg;base64,' + base64.b64encode(data).decode()}


def run_reference_search(profile, actor):
    """Busca un perfil de referencia en capturas y fichas; registra la consulta en la bitácora."""
    from services.search_matching_service import camera_captures, search_by_profile, similar_cases
    captures = camera_captures()
    results = search_by_profile(profile)
    fichas = similar_cases(profile.face_embedding, exclude_case_id=profile.case_id or None)
    summary = {'captures': len(captures),
               'events': sum(c.kind == 'EVENTO' for c in captures),
               'detections': sum(c.kind == 'DETECCION' for c in captures),
               'database': sum(c.kind == 'CAPTURA_BD' for c in captures),
               'fichas': len([c for c in store.cases if c.id != profile.case_id]),
               'found': len(results), 'duplicates': len(fichas)}
    subject = profile.case_id or profile.official_folio or 'referencia sin caso'
    store.audit(actor, 'Búsqueda',
                f'Búsqueda por ficha de {subject}: {summary["captures"]} captura(s) y {summary["fichas"]} ficha(s) '
                f'comparadas; {len(results)} aparición(es) posibles y {len(fichas)} ficha(s) parecidas. '
                'Consulta sin identificación.',
                case_id=profile.case_id or '—', result='CONSULTA')
    return results, fichas, summary
