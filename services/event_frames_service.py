"""Fotogramas de un evento y personas candidatas derivadas de ellos.

Este módulo no implementa reconocimiento facial: usa el motor que ya existe en
services/face_engine.py. Si el motor no está disponible, los fotogramas quedan marcados
como pendientes de integración en lugar de aparentar un análisis que no ocurrió.

Varias personas pueden aparecer cuando se escucha «ayuda». Cada una se guarda como
candidata asociada al evento, con su propio person_track_id. Ninguna se etiqueta víctima.
"""
from uuid import uuid4
import config
from models.event_frame import DetectedPersonCandidate, EventFrame
from services import store

TRACK_LABELS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'


def _frame_id(event_id, index):
    return f'{event_id}-F{index + 1:02d}'


def ensure_directories():
    directory = config.EVIDENCE_DIR / 'frames'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_frame(event_id, index, frame):
    """Guarda el fotograma junto a la evidencia. Nunca sobrescribe uno existente."""
    directory = ensure_directories()
    path = directory / f'{_frame_id(event_id, index)}.jpg'
    if path.exists():
        return path
    if isinstance(frame, (bytes, bytearray)):
        path.write_bytes(frame)  # ya viene comprimido del anillo: no se recodifica
    else:
        import cv2
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return path


AUDIO_CLIP_RATE = 48000  # AAC a 48 kHz: lo que cualquier navegador reproduce sin sorpresas


def _encode_audio(container, stream, audio, start):
    """Pista AAC alineada con el video: el segundo 0 del clip es el mismo en imagen y sonido."""
    from fractions import Fraction
    import av
    import numpy as np
    samples = np.clip(np.asarray(audio['samples'], dtype=np.float32).reshape(-1), -1, 1)
    rate = int(audio.get('rate') or config.AUDIO_SAMPLE_RATE)
    offset = 0.0 if audio.get('start_mono') is None or start is None else audio['start_mono'] - start
    if offset < 0:  # el audio empieza antes que el video: se recorta lo que sobra
        samples, offset = samples[int(round(-offset * rate)):], 0.0
    if not samples.size:
        return
    source = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format='flt', layout='mono')
    source.sample_rate = rate
    resampler = av.AudioResampler(format='fltp', layout='mono', rate=AUDIO_CLIP_RATE)
    fifo = av.AudioFifo()
    for chunk in resampler.resample(source) + resampler.resample(None):
        chunk.pts = None
        fifo.write(chunk)
    size = stream.codec_context.frame_size or 1024
    pts = int(round(offset * AUDIO_CLIP_RATE))
    while fifo.samples:
        chunk = fifo.read(size) if fifo.samples >= size else fifo.read()
        chunk.pts, chunk.time_base = pts, Fraction(1, AUDIO_CLIP_RATE)
        pts += chunk.samples
        for packet in stream.encode(chunk):
            container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)


def _encode_h264(path, frames, width, height, start=None, audio=None):
    """H.264 (+ AAC) en MP4, que es lo que un navegador sabe reproducir.

    Cada cuadro conserva el instante en que la cámara lo entregó: si la cámara se trabó un
    segundo, el clip dura lo que duró en realidad y el audio sigue sincronizado. El códec mp4v
    de OpenCV escribe un archivo válido que ningún navegador decodifica, y una evidencia que
    nadie puede ver no sirve para verificar nada. PyAV trae FFmpeg: no añade dependencias.
    """
    try:
        from fractions import Fraction
        import av
        import cv2
        # H.264 exige dimensiones pares.
        width, height = width - width % 2, height - height % 2
        if width <= 0 or height <= 0:
            return False
        origin = frames[0][0] if start is None else min(start, frames[0][0])
        span = max(frames[-1][0] - frames[0][0], .001)
        nominal = max(1, min(round(len(frames) / span), 30))
        # faststart deja el índice al principio: el navegador puede empezar sin descargarlo todo.
        with av.open(str(path), mode='w', options={'movflags': 'faststart'}) as container:
            stream = container.add_stream('libx264', rate=nominal)
            stream.width, stream.height, stream.pix_fmt = width, height, 'yuv420p'
            stream.options = {'crf': '26', 'preset': 'veryfast'}
            stream.codec_context.time_base = Fraction(1, 1000)
            sound = None
            if audio is not None and len(audio.get('samples', ())):
                sound = container.add_stream('aac', rate=AUDIO_CLIP_RATE, layout='mono')
            last = -1
            for moment, image in frames:
                if image.shape[:2] != (height, width):
                    image = cv2.resize(image, (width, height))
                frame = av.VideoFrame.from_ndarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), format='rgb24')
                last = max(last + 1, int(round((moment - origin) * 1000)))
                frame.pts, frame.time_base = last, Fraction(1, 1000)
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
            if sound is not None:
                _encode_audio(container, sound, audio, origin)
        return path.exists() and path.stat().st_size > 0
    except Exception:
        path.unlink(missing_ok=True)
        return False


def _encode_opencv(path, images, fps, width, height):
    """Último recurso si PyAV falla: el archivo queda, aunque el navegador no lo reproduzca."""
    import cv2
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))
    try:
        for image in images:
            writer.write(image if image.shape[:2] == (height, width) else cv2.resize(image, (width, height)))
    finally:
        writer.release()
    return path.exists() and path.stat().st_size > 0


def write_event_clip(event_id, camera_id, window, audio=None, reference=None, angle=False):
    """Escribe el clip del evento (video y, si lo hay, su audio) y lo asocia a la evidencia.

    `window` son los cuadros que el anillo conservaba alrededor de la frase; `reference`, el
    instante de la frase, y el clip empieza VIDEO_PRE_EVENT_SECONDS antes. Si no hay cuadros
    —cámara simulada o fuente no integrada— la evidencia lo dice en lugar de quedarse con un
    video vacío. `angle` marca un ángulo adicional de otra cámara del equipo.
    """
    from services.evidence_service import attach_video_evidence, file_hash, get_event
    event = get_event(event_id)
    if not window:
        if event and not angle:
            event.video_status = 'PENDING_INTEGRATION'
        return None
    config.EVIDENCE_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    path = config.EVIDENCE_VIDEO_DIR / (f'{event_id}-{camera_id}.mp4' if angle else f'{event_id}.mp4')
    if path.exists():
        return path
    from services.video_ring import VideoRing
    frames = [(moment, VideoRing.decode(payload)) for moment, _, payload in window]
    frames = [(moment, image) for moment, image in frames if image is not None]
    if not frames:
        return None
    height, width = frames[0][1].shape[:2]
    start = None if reference is None else reference - config.VIDEO_PRE_EVENT_SECONDS
    with_audio = _encode_h264(path, frames, width, height, start=start, audio=audio)
    if not with_audio:
        span = max(frames[-1][0] - frames[0][0], .001)
        _encode_opencv(path, [image for _, image in frames], max(1.0, min(len(frames) / span, 30.0)),
                       width, height)
    if not path.exists() or path.stat().st_size == 0:
        path.unlink(missing_ok=True)
        if event and not angle:
            event.video_status = 'PENDING_INTEGRATION'
        return None
    try:
        attach_video_evidence(event_id, path,
                              window[0][1].strftime('%Y-%m-%d %H:%M:%S'),
                              window[-1][1].strftime('%Y-%m-%d %H:%M:%S'),
                              integrity_hash=file_hash(path),
                              has_audio=bool(with_audio and audio is not None and len(audio.get('samples', ()))),
                              camera_id=camera_id, angle=angle)
    except ValueError:
        return None
    return path


def store_event_frames(event_id, camera_id, captures):
    """Registra los fotogramas pedidos alrededor del evento, existan o no las imágenes."""
    from services.evidence_service import project_path
    frames = []
    for index, capture in enumerate(captures):
        frame_id = _frame_id(event_id, index)
        when = capture['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
        if capture['frame'] is None:
            frames.append(EventFrame(frame_id, event_id, camera_id, when,
                                     processing_status='PENDIENTE_INTEGRACION',
                                     offset_seconds=capture['offset'],
                                     note=capture.get('reason') or
                                     'La fuente de video no entregó imagen en ese instante.'))
            continue
        path = _write_frame(event_id, index, capture['frame'])
        frames.append(EventFrame(frame_id, event_id, camera_id, when,
                                 image_path=project_path(path), processing_status='CAPTURADO',
                                 offset_seconds=capture['offset']))
    store.event_frames.extend(frames)
    stored = sum(f.processing_status == 'CAPTURADO' for f in frames)
    store.audit('Sistema', 'Evidencia',
                f'{stored} de {len(frames)} fotograma(s) conservados para {event_id}.'
                + ('' if stored else ' La fuente de video no entregó imagen (el motivo queda en cada fotograma).'),
                camera_id=camera_id, result='FOTOGRAMAS_CAPTURADOS' if stored else 'PENDIENTE_INTEGRACION')
    return frames


def get_event_frames(event_id):
    return [f for f in store.event_frames if f.event_id == event_id]


def get_event_candidates(event_id):
    return [c for c in store.person_candidates if c.event_id == event_id]


def _quality(face, frame):
    """Calidad aproximada: nitidez del recorte, tamaño y confianza de detección."""
    x1, y1, x2, y2 = [int(v) for v in face.bbox]
    height, width = frame.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(width, x2), min(height, y2)
    if x2 <= x1 or y2 <= y1:
        return 0.0, 0.0
    size = min(x2 - x1, y2 - y1)
    try:
        import cv2
        crop = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(crop, cv2.CV_64F).var())
    except Exception:
        sharpness = 0.0
    # Tres señales normalizadas: el rostro grande, nítido y bien detectado es mejor referencia.
    score = (min(size / 140, 1) * .4 + min(sharpness / 220, 1) * .3 + min(face.det_score, 1) * .3)
    return round(score, 3), sharpness


def process_event_frames(event_id):
    """Analiza los fotogramas del evento con el motor facial existente.

    Devuelve una persona candidata por rostro distinto hallado. Un rostro que reaparece en
    varios fotogramas se conserva una sola vez, con su mejor captura.
    """
    from services import face_engine
    from services.evidence_service import project_path
    frames = [f for f in get_event_frames(event_id) if f.processing_status == 'CAPTURADO']
    if not frames:
        return []
    if not face_engine.installed() or not face_engine.model_downloaded():
        for frame in frames:
            frame.processing_status = 'PENDIENTE_INTEGRACION'
            frame.note = 'Motor facial pendiente de integración: los fotogramas se conservan sin analizar.'
        store.audit('Sistema', 'Evidencia',
                    f'Fotogramas de {event_id} conservados sin análisis facial (motor no disponible).',
                    result='PENDIENTE_INTEGRACION')
        return []

    import cv2
    candidates = []
    for frame_record in frames:
        path = config.BASE_DIR / frame_record.image_path
        if not path.exists():
            continue
        image = cv2.imread(str(path))
        if image is None:
            continue
        try:
            faces = face_engine.analyze(image)
        except Exception as error:
            frame_record.processing_status = 'PENDIENTE_INTEGRACION'
            frame_record.note = f'El motor facial no pudo analizar el fotograma: {error}'
            continue
        frame_record.face_detected = bool(faces)
        frame_record.processing_status = 'PROCESADO' if faces else 'SIN_ROSTRO'
        from services.appearance_service import upper_clothing_color
        for face in faces:
            quality, _ = _quality(face, image)
            frame_record.quality_score = max(frame_record.quality_score or 0, quality)
            existing = _same_person(candidates, face)
            if existing:
                if quality > existing.face_quality:  # se conserva la mejor vista de esa persona
                    existing.face_quality = quality
                    existing.face_embedding = [float(v) for v in face.embedding]
                    existing.face_image_path = _save_face(event_id, existing.candidate_id, image, face)
                    existing.source_frame_id = frame_record.frame_id
                    existing.estimated_age = face.age if face.age is not None else existing.estimated_age
                    existing.clothing_color = upper_clothing_color(image, face.bbox) or existing.clothing_color
                continue
            candidate = DetectedPersonCandidate(
                candidate_id='PC-' + uuid4().hex[:8].upper(), event_id=event_id,
                camera_id=frame_record.camera_id, timestamp=frame_record.timestamp,
                person_track_id=f'PERSON-TRACK-{TRACK_LABELS[len(candidates) % len(TRACK_LABELS)]}',
                face_embedding=[float(v) for v in face.embedding], face_quality=quality,
                source_frame_id=frame_record.frame_id, source_type='EVENTO_AUXILIO',
                estimated_age=face.age, clothing_color=upper_clothing_color(image, face.bbox))
            candidate.face_image_path = _save_face(event_id, candidate.candidate_id, image, face)
            candidates.append(candidate)

    store.person_candidates.extend(candidates)
    if candidates:
        store.audit('Sistema', 'Coincidencia',
                    f'{len(candidates)} persona(s) candidata(s) asociadas a {event_id}. '
                    'Asociación al evento, no identificación.',
                    camera_id=frames[0].camera_id, result='CANDIDATOS_GENERADOS')
        # Sin que nadie lo pida: las personas del evento se buscan en las demás cámaras del
        # equipo (seguimiento provisional) y se comparan con todas las fichas activas.
        from services.search_matching_service import match_event_candidates
        from services.tracking_service import open_event_tracking
        open_event_tracking(event_id)
        match_event_candidates(event_id)
        try:  # con la base compartida conectada, las demás instancias también pueden buscarlas
            from services.db_service import compartir_capturas_evento
            compartir_capturas_evento(event_id)
        except Exception:
            pass
    return candidates


def _same_person(candidates, face):
    """Un rostro que reaparece entre fotogramas no es una persona nueva."""
    from services import face_engine
    for candidate in candidates:
        if not candidate.face_embedding:
            continue
        if face_engine.similarity(candidate.face_embedding, face.embedding) >= config.FACE_MATCH_THRESHOLD:
            return candidate
    return None


def _save_face(event_id, candidate_id, image, face):
    """Recorte del rostro de la persona candidata, para que una persona pueda revisarlo."""
    import cv2
    directory = ensure_directories()
    x1, y1, x2, y2 = [int(v) for v in face.bbox]
    margin = int(max(x2 - x1, y2 - y1) * .35)
    height, width = image.shape[:2]
    crop = image[max(0, y1 - margin):min(height, y2 + margin),
                 max(0, x1 - margin):min(width, x2 + margin)]
    if crop.size == 0:
        return ''
    path = directory / f'{event_id}-{candidate_id}.jpg'
    cv2.imwrite(str(path), crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
    from services.evidence_service import project_path
    return project_path(path)
