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


class LiveRecognitionError(ValueError):
    """The camera or the facial model cannot be used; the message is for the operator."""


def next_id(items, prefix):
    numbers = [int(item.id.rsplit('-', 1)[1]) for item in items if item.id.startswith(prefix + '-')]
    return f'{prefix}-{max(numbers, default=0) + 1:03d}'


def ascii_label(text):
    """OpenCV only draws ASCII: accents are dropped and demo suffixes removed."""
    text = (text or '').replace(' (ficticia)', '').replace(' (ficticio)', '')
    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()


def face_crop_data_url(frame, bbox, margin=.35, height=320):
    """JPEG data URL of a face with some margin, un-mirrored so it reads like a photograph."""
    import cv2
    x1, y1, x2, y2 = bbox
    dx, dy = int((x2 - x1) * margin), int((y2 - y1) * margin)
    crop = cv2.flip(frame[max(0, y1 - dy):y2 + dy, max(0, x1 - dx):x2 + dx], 1)
    if crop.shape[0] > height:
        crop = cv2.resize(crop, (max(1, round(crop.shape[1] * height / crop.shape[0])), height))
    data = cv2.imencode('.jpg', crop, [cv2.IMWRITE_JPEG_QUALITY, 88])[1]
    return 'data:image/jpeg;base64,' + base64.b64encode(data.tobytes()).decode()


def draw_face(image, face):
    """Box plus a filled label: folio, name, similarity and level, or «Sin coincidencia»."""
    import cv2
    x1, y1, x2, y2 = face['bbox']
    color = face_engine.LEVEL_COLORS[face['level']]
    label = (f'{face["case_id"]} {ascii_label(face["name"])} {face["similarity"]:.0%} {face["level"]}'
             if face['level'] else 'Sin coincidencia')
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
    # Sized for the compact 480-px view of the page.
    (width, height), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, .6, 1)
    top = max(0, y1 - height - baseline - 8)
    cv2.rectangle(image, (x1 - 1, top), (x1 + width + 10, top + height + baseline + 8), color, -1)
    cv2.putText(image, label, (x1 + 5, top + height + 4), cv2.FONT_HERSHEY_SIMPLEX, .6, (20, 20, 20), 1,
                cv2.LINE_AA)


class LiveRecognition:
    """Live camera recognition instance for a network camera."""

    def __init__(self, camera_id=None, camera_index=None, name='Cámara 1'):
        self.name = name
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
        self.detections = []  # detections created from the webcam, newest first
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads = []
        self._capture = None
        self._last_detection = {}  # (case_id, camera_id) -> (monotonic time, Detection)
        self._gallery_at = 0.0

    # ------------------------------------------------------------------ session
    def start(self, camera_id=None, camera_index=None, actor='Sistema'):
        if self.running:
            return
        try:
            face_engine.load()
        except face_engine.FaceEngineUnavailable as error:
            raise LiveRecognitionError(str(error)) from error
        import cv2
        index = self.camera_index if camera_index is None else int(camera_index)
        # DirectShow opens in about a second on Windows; the default backend can take several.
        capture = cv2.VideoCapture(index, cv2.CAP_DSHOW if sys.platform == 'win32' else cv2.CAP_ANY)
        if capture.isOpened():
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        if not capture.isOpened() or not capture.read()[0]:
            capture.release()
            raise LiveRecognitionError(f'No fue posible abrir el dispositivo {index}. '
                                       'Verifica que esté conectado y no esté siendo usado por otra app.')
        self.camera_id = camera_id or self.camera_id
        self.camera_index = index
        self.actor = actor
        self._capture = capture
        self._stop.clear()
        with self._lock:
            self._frame, self.faces = None, []
        self.error, self.dark, self.fps, self._gallery_at = None, False, 0.0, 0.0
        self.running, self.status = True, 'RECONOCIENDO'
        self._threads = [threading.Thread(target=self._capture_loop, name=f'live-capture-{self.camera_id}', daemon=True),
                         threading.Thread(target=self._analysis_loop, name=f'live-rec-{self.camera_id}', daemon=True)]
        for thread in self._threads:
            thread.start()
        store.audit(actor, 'Cámara', f'Inició el reconocimiento facial en vivo en {self.camera_id}',
                    camera_id=self.camera_id, result='RECONOCIENDO')

    def stop(self, actor=None):
        if not self.running:
            return
        self._stop.set()
        self.running = False
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout=3)
        self._threads = []
        capture, self._capture = self._capture, None
        if capture is not None:
            capture.release()
        with self._lock:
            self._frame, self.faces = None, []  # nothing seen outlives the session
        self.fps, self.dark, self.status = 0.0, False, 'DETENIDA'
        store.audit(actor or self.actor, 'Cámara', f'Detuvo el reconocimiento facial en vivo en {self.camera_id}',
                    camera_id=self.camera_id, result='DETENIDA')

    # ------------------------------------------------------------------ workers
    def _capture_loop(self):
        """Keeps only the newest frame, so the analysis never works on a stale one."""
        import cv2
        failures = 0
        while not self._stop.is_set():
            if self._capture is None:
                break
            ok, frame = self._capture.read()
            if not ok:
                failures += 1
                if failures == 30:
                    self.error, self.status = 'La cámara dejó de enviar imágenes.', 'SIN SEÑAL'
                time.sleep(.1)
                continue
            if failures >= 30:
                self.error, self.status = None, 'RECONOCIENDO'
            failures = 0
            with self._lock:
                self._frame = cv2.flip(frame, 1)  # mirror view

    def _analysis_loop(self):
        while not self._stop.is_set():
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
            elapsed = time.perf_counter() - started
            self.fps = 1 / max(elapsed, config.LIVE_ANALYSIS_INTERVAL_SECONDS)
            self._stop.wait(max(0.0, config.LIVE_ANALYSIS_INTERVAL_SECONDS - elapsed))
            while not self._stop.is_set() and self._frame is frame:  # wait for a new frame
                time.sleep(.01)

    def _refresh_gallery(self):
        """New cases and photos are picked up within a few seconds, without restarting."""
        if time.monotonic() - self._gallery_at < config.LIVE_GALLERY_REFRESH_SECONDS:
            return
        from services.facial_service import search_gallery
        self.gallery = search_gallery()
        self._gallery_at = time.monotonic()

    def _identify(self, face):
        """Best case for one face: its highest similarity over every reference photo."""
        best_case, best = None, 0.0
        for case, embedding in self.gallery:
            value = face_engine.similarity(face.embedding, embedding)
            if value > best:
                best_case, best = case, value
        level = face_engine.level_of(best) if best_case else None
        return {'bbox': face.bbox, 'det_score': face.det_score, 'embedding': face.embedding,
                'similarity': best, 'level': level,
                'case_id': best_case.id if level else None, 'name': best_case.person.name if level else None}

    def _record(self, frame, face):
        """One detection per case and camera in each window, keeping its best capture."""
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
                detection.capture = face_crop_data_url(frame, face['bbox'])
            return
        detection = Detection(next_id(store.detections, 'DET'), face['case_id'], self.camera_id, store.now(),
                              percent, quality=quality, capture=face_crop_data_url(frame, face['bbox']))
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
        return face_crop_data_url(frame, faces[0]['bbox'], margin=.6, height=480)

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
        return [{'capture': face_crop_data_url(frame, face['bbox']), 'case_id': face['case_id'],
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


# Instantiate dual live cameras for simultaneous multi-camera support
live_1 = LiveRecognition(config.DEFAULT_CAMERA_ID, config.CAMERA_INDEX, name='Cámara 1')
live_2 = LiveRecognition(config.SECOND_CAMERA_ID, config.CAMERA_INDEX_2, name='Cámara 2')

# Default alias for backwards compatibility
live = live_1

LIVE_INSTANCES = [live_1, live_2]


def get_live_for_camera(camera_id):
    """Returns the LiveRecognition instance managing camera_id, if any."""
    for inst in LIVE_INSTANCES:
        if inst.camera_id == camera_id:
            return inst
    return None


def is_live_camera(camera_id):
    """Returns True if the camera is one of the local equipment live cameras."""
    return get_live_for_camera(camera_id) is not None


def stop_all(actor=None):
    """Stops all active live recognition cameras."""
    for inst in LIVE_INSTANCES:
        if inst.running:
            inst.stop(actor)

