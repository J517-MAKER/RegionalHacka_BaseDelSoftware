"""Live facial recognition: webcam -> InsightFace -> people being searched -> detections.

The webcam is the one connected to the computer running NEXO, as the microphone is for
voice. Frames only live in memory. The only image kept is the face crop of a possible
match, attached to its detection so an operator can validate or discard it.
"""
import base64
import sys
import threading
import time
import unicodedata

import config
from models.detection import Detection
from models.match import Match
from services import face_engine, store
from services.video_ring import VideoRing


class LiveRecognitionError(ValueError):
    """The camera or the facial model cannot be used; the message is for the operator."""


def next_id(items, prefix):
    numbers = [int(item.id.rsplit('-', 1)[1]) for item in items if item.id.startswith(prefix + '-')]
    return f'{prefix}-{max(numbers, default=0) + 1:03d}'


def ascii_label(text):
    """OpenCV only draws ASCII: accents are dropped and demo suffixes removed."""
    text = (text or '').replace(' (ficticia)', '').replace(' (ficticio)', '')
    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()


def face_crop_data_url(frame, bbox, margin=.35, height=320, mirrored=True):
    """JPEG data URL of a face with some margin, un-mirrored so it reads like a photograph."""
    import cv2
    x1, y1, x2, y2 = bbox
    dx, dy = int((x2 - x1) * margin), int((y2 - y1) * margin)
    crop = frame[max(0, y1 - dy):y2 + dy, max(0, x1 - dx):x2 + dx]
    if mirrored:
        crop = cv2.flip(crop, 1)
    if crop.shape[0] > height:
        crop = cv2.resize(crop, (max(1, round(crop.shape[1] * height / crop.shape[0])), height))
    data = cv2.imencode('.jpg', crop, [cv2.IMWRITE_JPEG_QUALITY, 88])[1]
    return 'data:image/jpeg;base64,' + base64.b64encode(data.tobytes()).decode()


TRACK_COLOR = (200, 70, 160)  # BGR: morado, el del seguimiento en el mapa


def draw_face(image, face):
    """Box plus a filled label: folio, name and level, or «Sin coincidencia».

    Nunca se dibuja el porcentaje crudo junto al nombre: en la pantalla de la cámara se lee
    como una identificación, y aquí nadie la ha revisado todavía."""
    import cv2
    x1, y1, x2, y2 = face['bbox']
    color = face_engine.LEVEL_COLORS[face['level']]
    label = (f'{face["case_id"]} {ascii_label(face["name"])} {face["level"]}'
             if face['level'] else 'Sin coincidencia')
    if face.get('track_level'):
        # Persona vista en un evento de auxilio que reaparece: se distingue en morado.
        if not face['level']:
            color, label = TRACK_COLOR, f'SEGUIMIENTO {face["track_label"]}'
        else:
            label += ' / SEGUIMIENTO'
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
    # Sized for the compact 480-px view of the page.
    (width, height), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, .6, 1)
    top = max(0, y1 - height - baseline - 8)
    cv2.rectangle(image, (x1 - 1, top), (x1 + width + 10, top + height + baseline + 8), color, -1)
    cv2.putText(image, label, (x1 + 5, top + height + 4), cv2.FONT_HERSHEY_SIMPLEX, .6, (20, 20, 20), 1,
                cv2.LINE_AA)


# ---------------------------------------------------------------------- devices
# Physical cameras are told apart by their name, not by a fixed index: Windows renumbers
# them when a USB webcam is plugged or unplugged, and virtual cameras (OBS, phones) are
# listed among them.
# Enlace Móvil de Windows publica el celular como «<teléfono> (Windows Virtual Camera)».
PHONE_HINTS = ('windows virtual camera', 'droidcam', 'iriun', 'epoccam')
VIRTUAL_HINTS = ('virtual', 'obs', 'manycam', 'xsplit', 'snap camera', 'ndi')
BUILTIN_HINTS = ('integrated', 'integrada', 'built-in', 'builtin', 'internal', 'interna', 'facetime')
KIND_LABELS = {'laptop': 'Cámara de la laptop', 'usb': 'Webcam USB', 'phone': 'Cámara del celular',
               'virtual': 'Cámara virtual'}
MISSING_HINTS = {
    'phone': 'No se detectó la cámara del celular. Enlázalo en Configuración > Bluetooth y dispositivos > '
             'Dispositivos móviles, activa «Usar como cámara conectada» y pulsa «Detectar cámaras».',
}


def classify_device(name):
    """'laptop', 'usb' or 'virtual' from the name the operating system reports."""
    low = (name or '').lower()
    if any(hint in low for hint in PHONE_HINTS):
        return 'phone'
    if any(hint in low for hint in VIRTUAL_HINTS):
        return 'virtual'
    if any(hint in low for hint in BUILTIN_HINTS):
        return 'laptop'
    return 'usb'


def _directshow_names():
    """Video inputs in DirectShow order, which is the index order of cv2.CAP_DSHOW."""
    try:
        import comtypes
        try:
            comtypes.CoInitialize()  # needed in every thread that talks to COM
        except OSError:
            pass
        from pygrabber.dshow_graph import FilterGraph
        return [name.strip() for name in FilterGraph().get_input_devices()]
    except Exception:
        return None


def _probe_names(limit=4):
    """Fallback without device names: the indexes that open, skipping the ones in use."""
    import cv2
    busy = {inst.camera_index for inst in LIVE_INSTANCES if inst.running}
    names = []
    for index in range(limit):
        if index in busy:
            names.append(f'Dispositivo {index}')
            continue
        capture = cv2.VideoCapture(index, cv2.CAP_DSHOW if sys.platform == 'win32' else cv2.CAP_ANY)
        opened = capture.isOpened()
        capture.release()
        if not opened:
            break
        names.append(f'Dispositivo {index}')
    return names


def list_video_devices():
    """[{'index', 'name', 'kind'}] for every video input of this computer."""
    names = _directshow_names() if sys.platform == 'win32' else None
    probed = names is None
    if probed:
        names = _probe_names()
    devices = [{'index': i, 'name': name, 'kind': classify_device(name)} for i, name in enumerate(names)]
    if probed and devices:  # no names: the first device is usually the built-in one
        devices[0]['kind'] = 'laptop'
    elif not any(d['kind'] == 'laptop' for d in devices):
        physical = [d for d in devices if d['kind'] == 'usb']
        if len(physical) > 1:  # two unnamed physical cameras: the first one is the laptop's
            physical[0]['kind'] = 'laptop'
    return devices


def find_device(kind, exclude=(), devices=None):
    """First device of that kind whose index is not excluded, or None."""
    for device in list_video_devices() if devices is None else devices:
        if device['kind'] == kind and device['index'] not in exclude:
            return device
    return None


def device_name(index, devices=None):
    for device in list_video_devices() if devices is None else devices:
        if device['index'] == index:
            return device['name']
    return f'Dispositivo {index}'


def _same_picture(frame_a, frame_b):
    """True when two frames come from the same sensor (a camera mirrored through another index)."""
    import cv2
    if frame_a is None or frame_b is None:
        return False
    small = [cv2.cvtColor(cv2.resize(f, (64, 48)), cv2.COLOR_BGR2GRAY).astype('int16') for f in (frame_a, frame_b)]
    return float(abs(small[0] - small[1]).mean()) < 1.5


_start_lock = threading.Lock()


class LiveRecognition:
    """Live camera recognition instance for a network camera."""

    def __init__(self, camera_id=None, camera_index=None, name='Cámara 1', kind=None):
        self.name = name
        self.kind = kind  # 'laptop', 'usb' or 'phone': which physical camera this slot looks for
        # Las webcams se ven en espejo, como espera quien está frente a ellas; el celular apunta
        # a la escena (cámara trasera) y se muestra tal cual.
        self.mirror = kind != 'phone'
        # Quién la detuvo a propósito: el monitoreo continuo no reabre una cámara pausada.
        self.paused_by = ''
        self.device_name = None
        self.running = False
        self.status = 'DETENIDA'
        self.error = None
        self.dark = False
        self.camera_id = camera_id or config.DEFAULT_CAMERA_ID
        self.camera_index = config.CAMERA_INDEX if camera_index is None else camera_index
        self.actor = 'Sistema'
        self.fps = 0.0
        self.faces = []  # latest analysis, most prominent face first
        self.gallery = []  # (case, embedding) for every usable photo of the cases being searched
        self.watchlist = []  # (persona de un evento, huella) con seguimiento vigente
        self.detections = []  # detections created from the webcam, newest first
        # El reconocimiento facial es una capa sobre la transmisión, no su requisito: sin el
        # modelo la cámara sigue en vivo y grabando su anillo de evidencia.
        # INACTIVO · CARGANDO · ACTIVO · NO_DISPONIBLE
        self.recognition = 'INACTIVO'
        self.recognition_error = None
        self._model_retry_at = 0.0
        # Los últimos segundos de video, tal como los ve la cámara (sin espejo), para poder
        # reconstruir el antes y el después de una posible solicitud de auxilio.
        self.ring = VideoRing()
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads = []
        self._capture = None
        self._last_detection = {}  # (case_id, camera_id) -> (monotonic time, Detection)
        self._gallery_at = 0.0

    # ------------------------------------------------------------------ session
    def _others(self):
        return [inst for inst in LIVE_INSTANCES if inst is not self and inst.running]

    def _resolve_index(self, camera_index):
        """Device chosen by the operator, or the physical camera of this slot's kind."""
        if camera_index is not None:
            return int(camera_index), None
        if not self.kind:
            return self.camera_index, None
        devices = list_video_devices()
        busy = {inst.camera_index for inst in self._others()}
        device = find_device(self.kind, busy, devices)
        if device is None:
            label = KIND_LABELS[self.kind].lower()
            raise LiveRecognitionError(MISSING_HINTS.get(
                self.kind, f'No se detectó la {label}. Conéctala y pulsa «Detectar cámaras».'))
        return device['index'], device['name']

    def start(self, camera_id=None, camera_index=None, actor='Sistema'):
        if self.running:
            return
        with _start_lock:  # two slots never grab the same device at the same time
            # Se vuelve a mirar ya con el candado: el monitoreo continuo y el botón REANUDAR
            # pueden pedirlo a la vez, y el segundo no debe abrir otra vez la misma cámara.
            if self.running:
                return
            self._start(camera_id, camera_index, actor)

    def _start(self, camera_id, camera_index, actor):
        # No se espera al modelo facial: la cámara transmite y graba evidencia desde ya, y el
        # modelo se carga aparte, en el hilo de análisis (la primera vez puede descargarse).
        import cv2
        camera_id = camera_id or self.camera_id
        index, name = self._resolve_index(camera_index)
        for other in self._others():
            if other.camera_index == index:
                raise LiveRecognitionError(f'El dispositivo {index} ya lo usa {other.name}. '
                                           'Elige la otra cámara física.')
            if other.camera_id == camera_id:
                raise LiveRecognitionError(f'{camera_id} ya está asignada a {other.name}. '
                                           'Elige otra cámara de la red.')
        # DirectShow opens in about a second on Windows; the default backend can take several.
        capture = cv2.VideoCapture(index, cv2.CAP_DSHOW if sys.platform == 'win32' else cv2.CAP_ANY)
        if capture.isOpened() and hasattr(capture, 'set'):
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        ok, first = capture.read() if capture.isOpened() else (False, None)
        if not ok:
            capture.release()
            raise LiveRecognitionError(f'No fue posible abrir la cámara (dispositivo {index}). '
                                       'Verifica que esté conectada y que otra aplicación no la esté usando.')
        for other in self._others():
            with other._lock:
                seen = other._frame
            if seen is not None and _same_picture(cv2.flip(first, 1) if self.mirror else first, seen):
                capture.release()
                raise LiveRecognitionError(f'El dispositivo {index} muestra la misma imagen que {other.name}; '
                                           'es la misma cámara física. Elige otro dispositivo.')
        self.camera_id = camera_id
        self.camera_index = index
        self.device_name = name or (device_name(index) if self.kind else None)
        self.actor = actor
        self._capture = capture
        # Una señal de alto por sesión: un hilo de la sesión anterior que tardó en salir (por
        # ejemplo, descargando el modelo facial) conserva la suya, ya activada, y no revive.
        stop = self._stop = threading.Event()
        with self._lock:
            self._frame, self.faces = None, []
        self.error, self.dark, self.fps, self._gallery_at = None, False, 0.0, 0.0
        self.recognition, self.recognition_error, self._model_retry_at = 'CARGANDO', None, 0.0
        self.ring.clear()
        self.running, self.status = True, 'EN VIVO'
        self._threads = [threading.Thread(target=self._capture_loop, args=(capture, stop),
                                          name=f'live-capture-{self.camera_id}', daemon=True),
                         threading.Thread(target=self._analysis_loop, args=(stop,),
                                          name=f'live-rec-{self.camera_id}', daemon=True)]
        for thread in self._threads:
            thread.start()
        store.audit(actor, 'Cámara', f'Inició la transmisión en vivo de {self.camera_id}',
                    camera_id=self.camera_id, result='EN VIVO')

    def stop(self, actor=None):
        if not self.running:
            return
        self._stop.set()
        self.running = False
        threads, self._threads = self._threads, []
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(timeout=3)
        capture, self._capture = self._capture, None
        # El hilo de captura suelta la cámara al salir. Soltarla aquí con un read() todavía en
        # curso puede tumbar el proceso: sólo se hace si ningún hilo de la sesión sigue vivo.
        if capture is not None and not any(thread.is_alive() for thread in threads):
            capture.release()
        with self._lock:
            self._frame, self.faces = None, []  # nothing seen outlives the session
        self.ring.clear()  # el video que ningún evento reclamó tampoco
        self.fps, self.dark, self.status = 0.0, False, 'DETENIDA'
        self.recognition = 'INACTIVO'
        store.audit(actor or self.actor, 'Cámara', f'Detuvo la transmisión en vivo de {self.camera_id}',
                    camera_id=self.camera_id, result='DETENIDA')

    @property
    def live_status(self):
        """Estado para mostrar cuando la cámara transmite: con o sin reconocimiento."""
        if self.recognition == 'ACTIVO':
            return 'RECONOCIENDO'
        return 'EN VIVO'

    # ------------------------------------------------------------------ workers
    def _capture_loop(self, capture=None, stop=None):
        """Keeps only the newest frame, so the analysis never works on a stale one.

        Además alimenta el anillo de evidencia a ritmo constante, con el cuadro tal como lo
        entrega la cámara: la evidencia debe mostrar la escena como es, no en espejo. Un cuadro
        que no se puede leer o procesar cuenta como perdido: el hilo no muere en silencio
        dejando la imagen congelada y el anillo vacío. Al salir, suelta la cámara.
        """
        import cv2
        capture = self._capture if capture is None else capture
        stop = self._stop if stop is None else stop
        failures = 0
        try:
            while capture is not None and not stop.is_set():
                try:
                    ok, frame = capture.read()
                    if stop.is_set():  # la sesión terminó mientras se leía: el cuadro ya no es suyo
                        break
                    if ok:
                        if self.ring.due():
                            self.ring.write(frame)
                        shown = cv2.flip(frame, 1) if self.mirror else frame
                except Exception:  # controlador o cuadro dañado
                    ok = False
                if not ok:
                    failures += 1
                    if failures == 30:
                        self.error, self.status = 'La cámara dejó de enviar imágenes.', 'SIN SEÑAL'
                    time.sleep(.1)
                    continue
                if failures >= 30:
                    self.error, self.status = None, self.live_status
                failures = 0
                with self._lock:
                    self._frame = shown
        finally:
            if capture is not None:
                capture.release()

    def _ensure_recognition(self, stop=None):
        """Carga el modelo facial sin interrumpir la transmisión. True cuando ya puede analizar.

        Si el modelo falta o no carga, la cámara sigue en vivo y grabando; el motivo queda a la
        vista y se vuelve a intentar cada FACE_MODEL_RETRY_SECONDS (por si alguien lo descarga).
        La primera carga puede tardar minutos (descarga): si la sesión terminó mientras tanto,
        su resultado ya no cambia el estado de la ranura.
        """
        if self.recognition == 'ACTIVO':
            return True
        if time.monotonic() < self._model_retry_at:
            return False
        self.recognition = 'CARGANDO'
        try:
            face_engine.load()
        except face_engine.FaceEngineUnavailable as error:
            if stop is None or not stop.is_set():
                self.recognition, self.recognition_error = 'NO_DISPONIBLE', str(error)
                self._model_retry_at = time.monotonic() + config.FACE_MODEL_RETRY_SECONDS
            return False
        if stop is not None and stop.is_set():
            return False
        self.recognition, self.recognition_error = 'ACTIVO', None
        if self.status == 'EN VIVO':
            self.status = 'RECONOCIENDO'
        return True

    def _analysis_loop(self, stop=None):
        stop = self._stop if stop is None else stop
        while not stop.is_set():
            if not self._ensure_recognition(stop):
                stop.wait(1.0)
                continue
            with self._lock:
                frame = self._frame
            if frame is None:
                time.sleep(.05)
                continue
            started = time.perf_counter()
            try:
                self._refresh_gallery()
                faces = [self._identify(face) for face in face_engine.analyze(frame)]
            except Exception as error:  # the video keeps flowing; the operator sees the reason
                self.error = f'Error de reconocimiento: {error}'
                time.sleep(1)
                continue
            self.dark = float(frame.mean()) < 5
            with self._lock:
                self.faces = faces
            for face in faces:
                if face['level']:
                    self._record(frame, face)
                if face.get('track_level'):
                    self._record_sighting(frame, face)
            elapsed = time.perf_counter() - started
            self.fps = 1 / max(elapsed, config.LIVE_ANALYSIS_INTERVAL_SECONDS)
            stop.wait(max(0.0, config.LIVE_ANALYSIS_INTERVAL_SECONDS - elapsed))
            while not stop.is_set() and self._frame is frame:  # wait for a new frame
                time.sleep(.01)

    def _refresh_gallery(self):
        """New cases and photos are picked up within a few seconds, without restarting.

        También las personas de un evento de auxilio con seguimiento vigente: si reaparecen
        frente a esta cámara, queda un punto más de su trayecto.
        """
        if time.monotonic() - self._gallery_at < config.LIVE_GALLERY_REFRESH_SECONDS:
            return
        from services.facial_service import search_gallery
        from services.tracking_service import watch_targets
        self.gallery = search_gallery()
        self.watchlist = watch_targets()
        self._gallery_at = time.monotonic()

    def _identify(self, face):
        """Best case for one face: its highest similarity over every reference photo.

        Por separado, la persona de un evento en seguimiento a la que más se parece: un rostro
        puede ser a la vez parecido a una ficha y a alguien que estaba en un evento.
        """
        best_case, best = None, 0.0
        for case, embedding in self.gallery:
            value = face_engine.similarity(face.embedding, embedding)
            if value > best:
                best_case, best = case, value
        level = face_engine.level_of(best) if best_case else None
        track, track_best = None, 0.0
        for candidate, embedding in getattr(self, 'watchlist', ()):
            value = face_engine.similarity(face.embedding, embedding)
            if value > track_best:
                track, track_best = candidate, value
        track_level = face_engine.level_of(track_best) if track else None
        return {'bbox': face.bbox, 'det_score': face.det_score, 'embedding': face.embedding,
                'similarity': best, 'level': level, 'age': getattr(face, 'age', None),
                'case_id': best_case.id if level else None, 'name': best_case.person.name if level else None,
                'track': track if track_level else None, 'track_similarity': track_best,
                'track_level': track_level,
                'track_label': f'{track.person_track_id} {track.event_id}' if track_level else None}

    def _record_sighting(self, frame, face):
        """La persona de un evento reapareció frente a esta cámara: un punto más de su trayecto."""
        from services.tracking_service import record_sighting
        record_sighting(face['track'], self.camera_id, face['track_similarity'], face['track_level'],
                        face_crop_data_url(frame, face['bbox'], mirrored=self.mirror))

    def _record(self, frame, face):
        """One detection per case and camera in each window, keeping its best capture.

        La detección guarda también la huella y los rasgos estimados (edad aproximada y color de
        la ropa superior), para que una ficha registrada después pueda compararse contra ella.
        """
        from services.cameras_service import get_camera
        now, key = time.monotonic(), (face['case_id'], self.camera_id)
        x1, y1, x2, y2 = face['bbox']
        percent = round(face['similarity'] * 100)
        quality = 'Adecuada' if face['det_score'] >= .7 and min(x2 - x1, y2 - y1) >= 80 else 'Baja'
        last = self._last_detection.get(key)
        if last and now - last[0] < config.LIVE_DETECTION_COOLDOWN_SECONDS:
            detection = last[1]
            if percent > detection.similarity and detection.status == 'Pendiente de validación':
                detection.similarity, detection.quality = percent, quality
                detection.capture = face_crop_data_url(frame, face['bbox'], mirrored=self.mirror)
                detection.embedding = [float(v) for v in face['embedding']]
            return
        from services.appearance_service import upper_clothing_color
        detection = Detection(next_id(store.detections, 'DET'), face['case_id'], self.camera_id, store.now(),
                              percent, quality=quality, capture=face_crop_data_url(frame, face['bbox'], mirrored=self.mirror),
                              embedding=[float(v) for v in face['embedding']], estimated_age=face.get('age'),
                              clothing_color=upper_clothing_color(frame, face['bbox']))
        match = Match(next_id(store.matches, 'MAT'), detection.id)
        store.detections.insert(0, detection)
        store.matches.insert(0, match)
        self._last_detection[key] = (now, detection)
        self.detections.insert(0, {'detection': detection, 'match': match, 'name': face['name'],
                                   'level': face['level']})
        del self.detections[20:]
        camera = get_camera(self.camera_id)
        if camera:
            camera.status, camera.last_seen = 'Posible coincidencia', store.now()
        store.audit('Sistema', 'Coincidencia', f'Posible coincidencia facial en vivo · similitud {percent} %',
                    face['case_id'], self.camera_id, 'Pendiente de validación')

    # ------------------------------------------------------------------ interface
    def frame_jpeg(self):
        """Newest frame with boxes and labels for the browser; None when stopped."""
        import cv2
        with self._lock:
            frame, faces = self._frame, list(self.faces)
        if frame is None:
            return None
        view = frame.copy()
        for face in faces:
            draw_face(view, face)
        return cv2.imencode('.jpg', view, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()

    def capture_face_photo(self):
        """Portrait of the most prominent face in view, to register a person from the camera."""
        with self._lock:
            frame, faces = self._frame, list(self.faces)
        if frame is None:
            raise LiveRecognitionError('Inicia la cámara para tomar la fotografía.')
        if not faces:
            raise LiveRecognitionError('No hay un rostro en cuadro. Colócate de frente a la cámara.')
        return face_crop_data_url(frame, faces[0]['bbox'], margin=.6, height=480, mirrored=self.mirror)

    def gallery_counts(self):
        """Usable reference photos per case, as seen by the running session."""
        counts = {}
        for case, _ in self.gallery:
            counts[case.id] = counts.get(case.id, 0) + 1
        return counts

    def current_face(self, camera_id):
        """Most prominent face now in view of that camera, or None."""
        with self._lock:
            faces = list(self.faces)
        return faces[0] if self.running and camera_id == self.camera_id and faces else None

    def snapshot_faces(self, camera_id):
        """Face crops and matches in view of that camera right now; [] when it is not live."""
        if not self.running or camera_id != self.camera_id:
            return []
        with self._lock:
            frame, faces = self._frame, list(self.faces)
        if frame is None:
            return []
        return [{'capture': face_crop_data_url(frame, face['bbox'], mirrored=self.mirror), 'case_id': face['case_id'],
                 'name': face['name'], 'level': face['level'],
                 'similarity': round(face['similarity'] * 100) if face['level'] else None}
                for face in faces]

    @staticmethod
    def attach_faces_to_evidence(evidence, faces):
        """Keeps who was in view when a possible request for help was detected."""
        if faces:
            evidence.face_captures = faces
            store.audit('Sistema', 'Evidencia', f'{len(faces)} rostro(s) en cámara asociados a {evidence.event_id}',
                        camera_id=evidence.camera_id, result='ROSTROS_ASOCIADOS')
        return evidence.face_captures


# Two independent slots: the laptop's own camera and an external USB webcam.
live_1 = LiveRecognition(config.DEFAULT_CAMERA_ID, config.CAMERA_INDEX, name='Cámara 1 · Laptop', kind='laptop')
live_2 = LiveRecognition(config.SECOND_CAMERA_ID, config.CAMERA_INDEX_2, name='Cámara 2 · Webcam USB', kind='usb')

# Default alias for backwards compatibility
live = live_1

# Tercera ranura: el celular enlazado con Enlace Móvil de Windows.
live_3 = LiveRecognition(config.THIRD_CAMERA_ID, config.CAMERA_INDEX_3, name='Cámara 3 · Celular', kind='phone')

LIVE_INSTANCES = [live_1, live_2, live_3]


def get_live_for_camera(camera_id):
    """The slot showing camera_id: the running one first, so a stopped slot never hides it."""
    matches = [inst for inst in LIVE_INSTANCES if inst.camera_id == camera_id]
    return next((inst for inst in matches if inst.running), matches[0] if matches else None)


def running_for_camera(camera_id):
    """The slot running on camera_id right now, or None. `live` is read at call time."""
    for inst in [live, *LIVE_INSTANCES]:
        if inst.running and inst.camera_id == camera_id:
            return inst
    return None


def is_live_camera(camera_id):
    """Returns True if the camera is one of the local equipment live cameras."""
    return get_live_for_camera(camera_id) is not None


RECOGNITION_TEXT = {'ACTIVO': '● Reconocimiento facial activo',
                    'CARGANDO': '● Cargando el modelo facial (la cámara ya graba)',
                    'NO_DISPONIBLE': '● Sin reconocimiento facial (la cámara graba igual)'}


def recognition_text(inst):
    """Estado del reconocimiento de una ranura en palabras simples. La primera vez el modelo se
    descarga solo: se dice cuánto lleva, en lugar de pedirle a nadie que ejecute un comando."""
    if inst.recognition == 'CARGANDO' and not face_engine.model_downloaded():
        downloaded = face_engine.download_progress()
        return ('● Descargando el modelo facial por primera vez (unos 280 MB, sólo esta vez)'
                + (f': {downloaded:.0f} MB' if downloaded else '') + '. La cámara ya graba.')
    text = RECOGNITION_TEXT.get(inst.recognition, '')
    if inst.recognition == 'NO_DISPONIBLE' and inst.recognition_error:
        text += f': {inst.recognition_error}'
    return text


class _AnyLiveCamera:
    """Estado agregado de las dos ranuras, para enlazarlo desde la interfaz.

    Permite que el aviso «CÁMARA EN VIVO» del encabezado se ate a un dato en lugar de
    consultarse con un temporizador en cada página.
    """

    @property
    def running(self):
        return any(inst.running for inst in LIVE_INSTANCES)


any_live = _AnyLiveCamera()


def stop_all(actor=None):
    """Stops all active live recognition cameras."""
    for inst in LIVE_INSTANCES:
        if inst.running:
            inst.stop(actor)

