import hashlib
import config
from services import face_engine, store
from services.users_service import can, require
from services.db_service import buscar_coincidencias_rostro, guardar_captura_rostro

def get_detection(detection_id):
    """Busca y retorna una detección dentro del store."""
    return next((d for d in store.detections if d.id == detection_id), None)

def get_matches(case_id=None, vector_busqueda=None):
    """
    Recupera las coincidencias. 
    Si se provee un vector facial, realiza la búsqueda por similitud en PostgreSQL (pgvector).
    De lo contrario, consulta las coincidencias almacenadas en memoria (store).
    """
    if vector_busqueda is not None:  # un arreglo de numpy no puede evaluarse como booleano
        # Búsqueda vectorial directa en la base de datos de Docker, con el umbral de buffalo_l
        return buscar_coincidencias_rostro(vector_busqueda, umbral=config.FACE_MATCH_THRESHOLD)
    
    # Búsqueda tradicional en el store en memoria
    return [
        m for m in store.matches 
        if case_id is None or (get_detection(m.detection_id) and get_detection(m.detection_id).case_id == case_id)
    ]

def review_match(match_id, status):
    """Actualiza el estado de revisión de una coincidencia y genera un registro de auditoría.

    Un operador revisa en primer nivel; un supervisor resuelve lo que se le escaló. Sólo
    el operador puede escalar, porque enviarse trabajo a sí mismo no es una segunda revisión.
    Validar exige siempre al supervisor: un operador puede descartar o escalar, nunca dar
    por buena una coincidencia él solo.
    """
    if status == 'Validada por operador':
        actor = require('matches.supervise')
    elif status == 'En revisión':
        actor = require('matches.review')
    else:
        actor = require('matches.supervise') if can('matches.supervise') else require('matches.review')
    match = next(m for m in store.matches if m.id == match_id)
    match.status, match.reviewed_by, match.reviewed_at = status, actor, store.now()
    
    detection = get_detection(match.detection_id)
    if detection:
        detection.status = status
        store.audit(actor, 'Revisión', f'{match.id}: {status}', detection.case_id, detection.camera_id, status)
    
    return match

def validate_match(match_id):
    return review_match(match_id, 'Validada por operador')

def reject_match(match_id):
    return review_match(match_id, 'Descartada')

def request_review(match_id):
    return review_match(match_id, 'En revisión')

def registrar_rostro_detectado(codigo_camara, embedding_rostro, ruta_imagen, tipo_evento='ALERTA_AUDIO'):
    """Guarda el vector extraído de la cámara en PostgreSQL."""
    return guardar_captura_rostro(codigo_camara, embedding_rostro, ruta_imagen, tipo_evento)

_reference_faces = {}

def reference_face(photo):
    """Rostro principal de una fotografía de referencia (ruta o data URL), en caché por fotografía.

    Devuelve None si la imagen no tiene un rostro detectable o no es una imagen rasterizada (SVG)."""
    key = hashlib.sha1(str(photo).encode()).hexdigest()
    if key not in _reference_faces:
        _reference_faces[key] = face_engine.best_face(photo)
    return _reference_faces[key]

def search_gallery(cases=None):
    """(caso, huella) por cada fotografía utilizable de los casos que siguen en búsqueda."""
    active = [c for c in store.cases if c.status == 'En búsqueda'] if cases is None else cases
    return [(case, face.embedding) for case in active
            for face in map(reference_face, case.person.photos) if face is not None]

def compare_with_cases(embedding, cases=None):
    """Compara una huella facial con las fotografías de referencia de los casos registrados.

    Devuelve (candidatos, casos_comparados). Los candidatos superan FACE_MATCH_THRESHOLD y van
    del más parecido al menos parecido. Una similitud alta es una pista a revisar, nunca una identidad."""
    candidates, compared = [], 0
    for case in store.cases if cases is None else cases:
        faces = [face for face in map(reference_face, case.person.photos) if face is not None]
        if not faces:
            continue
        compared += 1
        score = max(face_engine.similarity(embedding, face.embedding) for face in faces)
        level = face_engine.level_of(score)
        if level:
            candidates.append({'case_id': case.id, 'name': case.person.name, 'similarity': round(score, 3),
                               'percent': round(score * 100), 'level': level,
                               'label': f'coincidencia facial {level.lower()}'})
    return sorted(candidates, key=lambda item: -item['similarity'])[:6], compared