"""Reads a search poster (image or PDF) and proposes a structured, editable record.

Nothing here identifies a person. OCR output, the cropped photo and every match are
proposals for human review. The facial comparison itself belongs to the facial module
(services/face_engine.py and services/facial_service.py): this service hands it the
cropped photo and shows what it returns.
"""
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import config
from models.alert_import_record import AlertImportRecord
from services import face_engine, store
from services.users_service import require

ACCEPTED_TYPES = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'application/pdf': '.pdf'}
SIGNATURES = ((b'\xff\xd8\xff', 'image/jpeg'), (b'\x89PNG', 'image/png'), (b'%PDF', 'application/pdf'))


def ensure_directories():
    for directory in (config.IMPORT_DOCUMENTS_DIR, config.IMPORT_PHOTOS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    return config.IMPORT_DIR


def detect_type(content, content_type=''):
    for signature, kind in SIGNATURES:
        if content.startswith(signature):
            return kind
    # WebP carries its marker inside the RIFF container, not at the start.
    if content[:4] == b'RIFF' and content[8:12] == b'WEBP':
        return 'image/webp'
    raise ValueError('El archivo no es una imagen JPG, PNG o WebP ni un PDF válido.')


def save_upload(content, content_type='', filename='', actor=None):
    """Stores the uploaded poster under a generated name; the original name is not trusted.

    From a worker thread (run.io_bound) pass the actor: the session is only readable in the UI context.
    """
    if actor is None:
        require('case')
    if not content:
        raise ValueError('El archivo está vacío.')
    if len(content) > config.IMPORT_MAX_BYTES:
        raise ValueError(f'El archivo supera el límite de {config.IMPORT_MAX_BYTES // (1024 * 1024)} MB.')
    kind = detect_type(content, content_type)
    ensure_directories()
    record_id = 'ALERT-' + datetime.now().strftime('%Y%m%d') + '-' + uuid4().hex[:6].upper()
    path = config.IMPORT_DOCUMENTS_DIR / (record_id + ACCEPTED_TYPES[kind])
    path.write_bytes(content)
    return record_id, path, kind


# --------------------------------------------------------------------------- OCR
def pdf_text_and_preview(path, record_id):
    """A PDF with a text layer needs no OCR; otherwise its first page is rendered."""
    import pymupdf
    with pymupdf.open(path) as document:
        page = document[0]
        text = page.get_text().strip()
        preview = config.IMPORT_DOCUMENTS_DIR / (record_id + '-preview.png')
        page.get_pixmap(dpi=config.IMPORT_RENDER_DPI).save(preview)
        images = []
        for info in page.get_images(full=True):
            base = document.extract_image(info[0])
            images.append(base['image'])
    return text, preview, images


def tesseract_ocr(image_path):
    import pytesseract
    from PIL import Image
    return pytesseract.image_to_string(Image.open(image_path), lang=config.OCR_LANGUAGE).strip()


def rapid_ocr(image_path):
    from rapidocr_onnxruntime import RapidOCR
    global _rapid
    if _rapid is None:
        _rapid = RapidOCR()
    result, _ = _rapid(str(image_path))
    return '\n'.join(line[1] for line in (result or [])).strip()


_rapid = None
# Ordered by preference; the first engine that works is used. Both are optional.
OCR_ENGINES = (('Tesseract', tesseract_ocr), ('RapidOCR', rapid_ocr))


def read_text(image_path):
    errors = []
    for name, engine in OCR_ENGINES:
        try:
            text = engine(image_path)
            if text:
                return text, name
            errors.append(f'{name}: sin texto')
        except Exception as exc:
            errors.append(f'{name}: {type(exc).__name__}')
    return '', '; '.join(errors)


# ------------------------------------------------------------------- photo crop
def crop_photo(image_path, record_id, embedded=()):
    """Tries the embedded image, then a face, then the largest photo-like region."""
    ensure_directories()
    target = config.IMPORT_PHOTOS_DIR / (record_id + '.png')
    for data in embedded:
        try:
            import cv2
            import numpy as np
            image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is not None and min(image.shape[:2]) >= 120 and .4 <= image.shape[1] / image.shape[0] <= 1.6:
                cv2.imwrite(str(target), image)
                return target, 'Imagen incrustada en el PDF'
        except Exception:
            break
    try:
        import cv2
        import numpy as np
        image = cv2.imread(str(image_path))
        if image is None:
            return None, 'No fue posible leer la imagen.'
        height, width = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        box, reason = find_face(gray, width, height), 'Rostro detectado'
        if box is None:
            box, reason = find_photo_region(gray, width, height), 'Región fotográfica estimada'
        if box is None:
            return None, 'No se detectó una fotografía; revisa el documento completo.'
        x, y, w, h = box
        cv2.imwrite(str(target), image[max(0, y):y + h, max(0, x):x + w])
        return target, reason
    except Exception:
        return None, 'Recorte automático no disponible en este equipo.'


def find_face(gray, width, height):
    import cv2
    path = Path(cv2.data.haarcascades) / 'haarcascade_frontalface_default.xml'
    if not path.exists():
        return None
    faces = cv2.CascadeClassifier(str(path)).detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    # Widen the face box into a portrait crop the facial module can work with.
    margin_x, margin_y = int(w * .6), int(h * .8)
    x, y = max(0, x - margin_x), max(0, y - margin_y)
    return x, y, min(width - x, w + 2 * margin_x), min(height - y, h + 2 * margin_y)


def find_photo_region(gray, width, height):
    """Largest dark-enough rectangle with portrait proportions, a heuristic only."""
    import cv2
    mask = cv2.threshold(cv2.GaussianBlur(gray, (5, 5), 0), 245, 255, cv2.THRESH_BINARY_INV)[1]
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25)))
    contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    page = width * height
    best = None
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        ratio, area = w / max(h, 1), w * h
        if .45 <= ratio <= 1.5 and .03 * page <= area <= .55 * page and (best is None or area > best[2] * best[3]):
            best = (x, y, w, h)
    return best


# ---------------------------------------------------------------- field parsing
LABELS = {
    'person_name': r'nombre(?:\s+completo)?(?:\s+de\s+la\s+persona)?',
    'folio': r'(?:folio|no\.?\s*de\s*alerta|numero\s+de\s+alerta|alerta\s+n[uú]mero|cedula\s+de\s+identificaci[oó]n)',
    'age': r'edad(?:\s+aproximada)?',
    'sex': r'(?:sexo|g[eé]nero)',
    'nationality': r'nacionalidad',
    'date_of_disappearance': r'fecha\s+de\s+(?:desaparici[oó]n|los\s+hechos|hechos|extrav[ií]o)',
    'date_of_report': r'fecha\s+de(?:l)?\s+(?:reporte|denuncia|registro)',
    'location': r'(?:lugar|domicilio|direcci[oó]n|municipio|localidad)\s*(?:de\s+(?:desaparici[oó]n|los\s+hechos|hechos))?',
    'physical': r'(?:media\s+filiaci[oó]n|descripci[oó]n\s+f[ií]sica|complexi[oó]n|estatura|tez|color\s+de\s+piel)',
    'marks': r'se[nñ]as\s+particulares',
    'clothing': r'(?:vestimenta|vest[ií]a|ropa|prendas)',
    'authority': r'(?:autoridad(?:\s+emisora)?|fiscal[ií]a|procuradur[ií]a|comisi[oó]n\s+de\s+b[uú]squeda)',
    'investigation': r'(?:carpeta\s+de\s+investigaci[oó]n|expediente|averiguaci[oó]n\s+previa)',
}
FIELD_OF_LABEL = {'sex': 'sex_reported', 'location': 'location_of_events', 'physical': 'physical_description',
                  'marks': 'distinctive_marks', 'clothing': 'clothing_description',
                  'authority': 'authority', 'investigation': 'investigation_file'}


def clean(value):
    value = re.sub(r'\s+', ' ', (value or '')).strip(' .:;,-—·|')
    return value or None


def compact(text):
    """OCR often glues bold words together, so labels are matched without separators."""
    return re.sub(r'[^a-z0-9]', '', strip_accents(text or '').lower())


# Patterns are matched against the compacted label, so spacing never breaks a match.
COMPACT_LABELS = {key: re.compile(re.sub(r'\\s[+*]', '', pattern) + '$') for key, pattern in LABELS.items()}


def label_of(line):
    head = re.split(r'[:：]', line, maxsplit=1)[0]
    if len(head) > 60:
        return None
    key = compact(head)
    return next((name for name, pattern in COMPACT_LABELS.items() if pattern.match(key)), None) if key else None


def split_words(value):
    """Restores spacing in values the OCR glued, e.g. ElenaRoblesMartinez."""
    return re.sub(r'(?<=[a-zá-ú])(?=[A-ZÁ-Ú])', ' ', value or '')


def parse_fields(text):
    """Label-driven reading: value on the same line, otherwise the next free line."""
    lines = [line.strip() for line in (text or '').splitlines()]
    labels = [label_of(line) for line in lines]
    found = {}
    for index, line in enumerate(lines):
        key = labels[index]
        if not key or key in found:
            continue
        parts = re.split(r'[:：]', line, maxsplit=1)
        value = parts[1] if len(parts) > 1 else ''
        if not clean(value):
            value = next((lines[j] for j in range(index + 1, min(index + 3, len(lines)))
                          if lines[j] and labels[j] is None), '')
        if clean(value):
            found[key] = clean(value)
    result = {FIELD_OF_LABEL.get(key, key): value for key, value in found.items()}
    if result.get('person_name'):
        result['person_name'] = split_words(result['person_name'])
    if result.get('age'):
        digits = re.search(r'\d{1,3}', result['age'])
        result['age'] = digits[0] if digits else result['age']
    for key in ('date_of_disappearance', 'date_of_report'):
        if result.get(key):
            result[key] = normalize_date(result[key]) or result[key]
    return result


MONTHS = {'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6, 'julio': 7,
          'agosto': 8, 'septiembre': 9, 'setiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12}


def normalize_date(value):
    """Accepts 22 de septiembre de 2026, 23/09/2026 and 2026-09-22, glued or spaced."""
    glued = compact(value)
    for name, number in MONTHS.items():
        match = re.search(rf'(\d{{1,2}})(?:de)?{name}(?:de)?(\d{{4}})', glued)
        if match:
            return f'{match[2]}-{number:02d}-{int(match[1]):02d}'
    text = strip_accents(value or '').lower()
    match = re.search(r'(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})', text)
    if match:
        return f'{match[1]}-{int(match[2]):02d}-{int(match[3]):02d}'
    match = re.search(r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})', text)
    if match:
        year = match[3] if len(match[3]) == 4 else '20' + match[3]
        return f'{year}-{int(match[2]):02d}-{int(match[1]):02d}'
    return None


def strip_accents(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text or '') if unicodedata.category(c) != 'Mn')


# ------------------------------------------------------------------- extraction
def analyze_alert(record_id, path, kind, actor=None):
    """Full reading pass. A failure in any stage degrades to manual completion."""
    actor = actor or require('case')
    record = AlertImportRecord(id=record_id, source_file=project_path(path), source_type=kind,
                               imported_at=store.now(), imported_by=actor)
    embedded, notes = (), []
    image_path = path
    if kind == 'application/pdf':
        try:
            text, preview, embedded = pdf_text_and_preview(path, record_id)
            image_path = preview
            record.preview_path = project_path(preview)
            if text:
                record.ocr_text, record.ocr_engine = text, 'Texto incrustado en el PDF'
        except Exception:
            notes.append('No fue posible procesar el PDF; súbelo como imagen.')
    else:
        record.preview_path = project_path(path)
    if not record.ocr_text:
        text, engine = read_text(image_path)
        record.ocr_text, record.ocr_engine = text, engine
    if record.ocr_text:
        for key, value in parse_fields(record.ocr_text).items():
            setattr(record, key, value)
        missing = [key for key in ('person_name', 'date_of_disappearance', 'location_of_events')
                   if not getattr(record, key)]
        record.extraction_status = 'EXTRACCION_PARCIAL' if missing else 'EXTRACCION_COMPLETA'
        if missing:
            notes.append('Revisa los campos que no pudieron leerse.')
    else:
        record.extraction_status = 'SIN_TEXTO_RECONOCIDO'
        notes.append('No se reconoció texto. Captura los datos manualmente.')
    photo, reason = crop_photo(image_path, record_id, embedded)
    record.photo_path = project_path(photo) if photo else ''
    notes.append(reason)
    record.extraction_notes = ' '.join(notes)
    store.imports.insert(0, record)
    store.audit(actor, 'Importación', f'{record.id}: alerta analizada ({record.extraction_status})',
                result=record.extraction_status)
    return record


def project_path(path):
    try:
        return Path(path).relative_to(config.BASE_DIR).as_posix()
    except ValueError:
        return Path(path).as_posix()


def get_imports():
    return store.imports


def get_import(record_id):
    record = next((r for r in store.imports if r.id == record_id), None)
    if not record:
        raise ValueError('No se encontró la alerta importada.')
    return record


def update_fields(record_id, values):
    """The operator corrects what the reading got wrong; corrections are audited."""
    actor = require('case')
    record = get_import(record_id)
    changed = []
    for key, value in values.items():
        if not hasattr(record, key) or key in ('id', 'source_file', 'photo_path', 'ocr_text'):
            continue
        value = (str(value).strip() or None) if value is not None else None
        if getattr(record, key) != value:
            changed.append(key)
            setattr(record, key, value)
    if changed:
        record.extraction_status = 'REVISADA_POR_OPERADOR'
        store.audit(actor, 'Importación', f'{record.id}: {len(changed)} campo(s) corregido(s) manualmente',
                    result='REVISADA_POR_OPERADOR')
    return record


# ------------------------------------------------- facial module integration point
def prepare_face_reference(photo_path):
    """Detects the face in the cropped photo and computes its 512-number embedding.

    Without InsightFace installed the reference is only prepared, as a mock, and no level
    is ever assigned: that would be a match nobody calculated.
    """
    path = Path(photo_path) if photo_path else None
    if not path or not (config.BASE_DIR / path).exists() and not path.exists():
        return {'status': 'SIN_FOTOGRAFIA', 'reference': None,
                'message': 'No hay fotografía recortada para preparar una referencia.'}
    reference = {'reference': project_path(path), 'prepared_at': store.now()}
    if not face_engine.installed():
        return {**reference, 'status': 'REFERENCIA_PREPARADA', 'mock': True,
                'message': 'Referencia lista para el módulo de reconocimiento facial.'}
    try:
        face = face_engine.best_face(config.BASE_DIR / path if (config.BASE_DIR / path).exists() else path)
    except face_engine.FaceEngineUnavailable as error:
        return {**reference, 'status': 'ERROR_MODULO_FACIAL', 'mock': False, 'message': str(error)}
    if face is None:
        return {**reference, 'status': 'SIN_ROSTRO_DETECTADO', 'mock': False,
                'message': 'No se detectó un rostro en la fotografía recortada; no se generó la huella facial.'}
    return {**reference, 'status': 'REFERENCIA_PREPARADA', 'mock': False, 'engine': face_engine.ENGINE_NAME,
            'embedding': face.embedding.tolist(), 'det_score': round(face.det_score, 3),
            'message': 'Huella facial generada.'}


def match_face_reference(face_reference):
    """Compares a real reference with the photos of the registered cases.

    Mock references keep the previous behaviour: the candidate cameras stay pending.
    """
    if not face_reference or face_reference.get('status', 'SIN_FOTOGRAFIA') == 'SIN_FOTOGRAFIA':
        return {'status': 'SIN_FOTOGRAFIA', 'mock': True, 'candidates': []}
    if face_reference['status'] != 'REFERENCIA_PREPARADA':  # no face, or the engine failed
        return {'status': face_reference['status'], 'mock': False, 'candidates': [],
                'message': face_reference.get('message', '')}
    if face_reference.get('mock') or 'embedding' not in face_reference:
        from services.cameras_service import get_cameras
        candidates = [{'camera_id': camera.id, 'location': camera.location,
                       'result': 'Pendiente del módulo facial'}
                      for camera in get_cameras() if camera.status != 'Desconectada'][:6]
        return {'status': 'PENDIENTE_MODULO_FACIAL', 'mock': True, 'candidates': candidates,
                'message': 'Comparación facial pendiente de integración. No se asignan niveles automáticos.'}
    from services.facial_service import compare_with_cases
    try:
        candidates, compared = compare_with_cases(face_reference['embedding'])
    except face_engine.FaceEngineUnavailable as error:
        return {'status': 'ERROR_MODULO_FACIAL', 'mock': False, 'candidates': [], 'message': str(error)}
    if candidates:
        message = f'Comparada con {compared} caso(s) con fotografía utilizable.'
    elif compared:
        message = f'Huella facial generada. Se comparó con {compared} caso(s) con fotografía y ninguno supera el umbral.'
    else:
        message = 'Huella facial generada. Aún no hay casos con fotografías reales para comparar.'
    return {'status': 'COINCIDENCIAS_FACIALES' if candidates else 'SIN_COINCIDENCIAS_FACIALES',
            'mock': False, 'candidates': candidates, 'compared_cases': compared,
            'message': message + ' La búsqueda en cámaras queda pendiente del módulo de video.'}


def compare_with_face_database(reference_photo):
    """Convenience wrapper for the facial module: prepare plus compare."""
    return match_face_reference(prepare_face_reference(reference_photo))


# ------------------------------------------------------------- textual matching
STOPWORDS = {'de', 'la', 'el', 'los', 'las', 'del', 'y', 'en', 'calle', 'avenida', 'col', 'colonia'}


def tokens(value):
    text = strip_accents(str(value or '')).lower().replace('(', ' ').replace(')', ' ')
    return [word for word in re.split(r'[^a-z0-9]+', text) if len(word) > 2 and word not in STOPWORDS]


def overlap(first, second):
    a, b = set(tokens(first)), set(tokens(second))
    return len(a & b) / len(a | b) if a and b else 0.0


def days_between(first, second):
    try:
        return abs((datetime.strptime(str(first)[:10], '%Y-%m-%d')
                    - datetime.strptime(str(second)[:10], '%Y-%m-%d')).days)
    except Exception:
        return None


def score_case(record, case):
    """Similarity only. A high score is a lead for a person to check, not an identity."""
    score, reasons = 0, []
    person = case.person
    clean_name = person.name.replace('(ficticia)', '').replace('(ficticio)', '')
    name_overlap = overlap(record.person_name, clean_name)
    if name_overlap:
        score += int(45 * name_overlap)
        reasons.append('Nombre coincidente' if name_overlap > .99 else 'Nombre similar')
    if record.sex_reported and person.sex and \
            strip_accents(record.sex_reported).lower()[:4] == strip_accents(person.sex).lower()[:4]:
        score += 8
        reasons.append('Sexo reportado compatible')
    if record.age and str(person.age).isdigit() and re.search(r'\d+', record.age):
        difference = abs(int(re.search(r'\d+', record.age)[0]) - int(person.age))
        if difference <= 3:
            score += 12 - difference * 2
            reasons.append('Edad coincidente' if difference == 0 else 'Edad dentro del rango')
    if overlap(record.location_of_events, f'{case.location} {case.zone}'):
        score += 15
        reasons.append('Lugar compatible')
    distance = days_between(record.date_of_disappearance or '', case.missing_date or '')
    if distance is not None and distance <= config.IMPORT_DATE_WINDOW_DAYS:
        score += 12 if distance == 0 else 6
        reasons.append('Misma fecha de desaparición' if distance == 0 else 'Fecha dentro del rango')
    for value, other, label in ((record.distinctive_marks, person.marks, 'Señas particulares similares'),
                                (record.clothing_description, person.clothing, 'Vestimenta similar'),
                                (record.physical_description, f'{person.build} {person.skin} {person.height}',
                                 'Descripción física similar')):
        if overlap(value, other) >= .2:
            score += 8
            reasons.append(label)
    return min(score, 100), reasons


def level_of(score):
    return 'ALTA' if score >= 60 else 'MEDIA' if score >= 35 else 'BAJA'


def text_matches(record):
    from services.cases_service import get_cases
    results = []
    for case in get_cases():
        score, reasons = score_case(record, case)
        if score >= 25:
            level = level_of(score)
            results.append({'case_id': case.id, 'name': case.person.name, 'score': score, 'level': level,
                            'reasons': reasons, 'label': f'coincidencia textual {level.lower()}'})
    return sorted(results, key=lambda item: -item['score'])[:6]


# ------------------------------------------------------------ contextual matching
def context_matches(record):
    """Zone, date range and related cameras. Never a claim about where the person is."""
    from services.cameras_service import get_cameras
    results = []
    place = record.location_of_events or ''
    cameras = [c for c in get_cameras() if overlap(place, f'{c.name} {c.location} {c.zone}') > 0] if place else []
    if cameras:
        results.append({'kind': 'Zona', 'level': 'MEDIA', 'cameras': [c.id for c in cameras[:4]],
                        'text': 'Zona compatible con el último lugar reportado: '
                                + ', '.join(c.id for c in cameras[:4]) + '.'})
    elif place:
        results.append({'kind': 'Zona', 'level': 'BAJA', 'cameras': [],
                        'text': 'No se encontraron cámaras asociadas al lugar reportado.'})
    if record.date_of_disappearance:
        near = [d for d in store.detections
                if (days_between(record.date_of_disappearance, d.timestamp) or 999) <= config.IMPORT_DATE_WINDOW_DAYS]
        results.append({'kind': 'Fecha', 'level': 'MEDIA' if near else 'BAJA',
                        'cameras': sorted({d.camera_id for d in near})[:4],
                        'text': f'{len(near)} detección(es) dentro de {config.IMPORT_DATE_WINDOW_DAYS} días '
                                'de la fecha reportada.' if near else
                                'Sin detecciones dentro del rango temporal reportado.'})
    related = sorted({camera for match in results for camera in match['cameras']})
    if related:
        results.append({'kind': 'Cámaras', 'level': 'MEDIA', 'cameras': related,
                        'text': f'Cámaras relacionadas encontradas: {len(related)}.'})
    if not results:
        results.append({'kind': 'Contexto', 'level': 'BAJA', 'cameras': [],
                        'text': 'Sin lugar ni fecha suficientes para un cruce contextual.'})
    return results


def run_matching(record_id, actor=None):
    """Runs the three comparisons. Every result stays pending human validation."""
    actor = actor or require('case')
    record = get_import(record_id)
    record.text_matches = text_matches(record)
    record.text_match_status = 'COINCIDENCIAS_ENCONTRADAS' if record.text_matches else 'SIN_COINCIDENCIAS'
    record.context_matches = context_matches(record)
    record.context_match_status = 'ANALIZADO'
    reference = prepare_face_reference(record.photo_path)
    facial = match_face_reference(reference)
    record.face_reference_status = reference['status'] if facial['status'] == 'SIN_FOTOGRAFIA' else facial['status']
    record.face_matches = facial['candidates']
    record.face_message = facial.get('message', '')
    record.review_status = 'PENDIENTE_VALIDACION'
    store.audit(actor, 'Importación',
                f'{record.id}: {len(record.text_matches)} coincidencia(s) textual(es); referencia facial '
                f'{record.face_reference_status}', result='PENDIENTE_VALIDACION')
    return record


# ------------------------------------------------------------------ final actions
def create_case_from_alert(record_id):
    from services.cases_service import create_case, photo_data_url
    actor = require('case')
    record = get_import(record_id)
    if record.linked_case_id:
        raise ValueError('Esta alerta ya está vinculada a un caso.')
    if not record.person_name:
        raise ValueError('Captura al menos el nombre antes de crear el caso.')
    data = record.as_case_data()
    photo = config.BASE_DIR / record.photo_path if record.photo_path else None
    if photo and photo.exists():
        data['photos'] = [photo_data_url(photo.read_bytes(), 'image/png')]
    case = create_case(data)
    record.linked_case_id, record.review_status = case.id, 'CASO_CREADO'
    store.audit(actor, 'Importación', f'{record.id}: caso {case.id} creado desde la alerta importada',
                case.id, result='CASO_CREADO')
    return case


def link_to_case(record_id, case_id):
    from services.cases_service import get_case
    actor = require('case')
    record = get_import(record_id)
    case = get_case(case_id)
    if not case:
        raise ValueError('No se encontró el caso indicado.')
    record.linked_case_id, record.review_status = case.id, 'VINCULADA_A_CASO'
    store.audit(actor, 'Importación', f'{record.id}: alerta vinculada al caso {case.id}; pendiente de validación',
                case.id, result='VINCULADA_A_CASO')
    return case


def send_to_review(record_id, notes=''):
    actor = require('case')
    record = get_import(record_id)
    record.review_status, record.review_notes = 'EN_REVISION', (notes or '')[:500]
    store.audit(actor, 'Importación', f'{record.id}: enviada a revisión', result='EN_REVISION')
    return record


def cancel_import(record_id):
    """Cancelling deletes the temporary files: an unused poster is not kept."""
    actor = require('case')
    record = get_import(record_id)
    if record.linked_case_id:
        raise ValueError('No se puede cancelar una alerta ya vinculada a un caso.')
    for value in (record.source_file, record.preview_path, record.photo_path):
        path = config.BASE_DIR / value if value else None
        if path and path.exists():
            path.unlink(missing_ok=True)
    store.imports.remove(record)
    store.audit(actor, 'Importación', f'{record.id}: importación cancelada y archivos temporales eliminados',
                result='CANCELADA')
    return record
