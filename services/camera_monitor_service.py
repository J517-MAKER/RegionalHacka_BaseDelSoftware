"""Monitoreo continuo de cámaras.

Modelo conceptual: las cámaras de seguridad ya están funcionando. Nadie las "inicia" desde
la interfaz; NEXO consume lo que emiten. Por eso el estado de una cámara es CAMERA_STREAM_ACTIVE
por sí mismo, y no la consecuencia de que un operador haya pulsado un botón.

El resto del sistema no sabe si detrás de una cámara hay una webcam, un archivo de video o
una fuente simulada: pide fotogramas a un adapter y recibe lo que haya, o una declaración
honesta de que esa fuente todavía no está integrada. Nunca se simula una detección real.

Retención: el anillo de video guarda unos segundos y se sobrescribe. Sólo cuando ocurre un
evento se conserva el fragmento alrededor de él. Buffer temporal, detección relevante,
evidencia y caso de búsqueda son cuatro cosas distintas.
"""
import os
import threading
import time
from datetime import datetime, timedelta
import config
from services import store


def autostart_enabled():
    """La cámara del equipo se enciende sola con el servidor.

    Se desactiva durante las pruebas: abrir la webcam real en mitad de una prueba pelearía
    con las sesiones que ellas mismas arrancan, y el dispositivo es de uso exclusivo.
    """
    return config.CAMERA_AUTOSTART and 'PYTEST_CURRENT_TEST' not in os.environ


class VideoRing:
    """Anillo de fotogramas en memoria. Lo que no se reclama, se pierde.

    Los cuadros se guardan comprimidos en JPEG: en crudo, medio minuto de una cámara a
    640x480 ocuparía cientos de megabytes por cámara, y aquí sólo hacen falta para poder
    reconstruir los segundos alrededor de un evento.
    """

    def __init__(self, seconds=None, fps=None):
        self.seconds = seconds or config.VIDEO_RING_SECONDS
        self.fps = fps or config.VIDEO_RING_FPS
        self.capacity = max(1, int(self.seconds * self.fps))
        self.frames = []  # [(monotonic, wall_clock, jpeg_bytes)]
        self.lock = threading.Lock()

    @staticmethod
    def encode(frame):
        import cv2
        ok, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buffer.tobytes() if ok else None

    @staticmethod
    def decode(payload):
        import cv2
        import numpy as np
        return cv2.imdecode(np.frombuffer(payload, dtype='uint8'), cv2.IMREAD_COLOR)

    def write(self, frame, when=None):
        payload = frame if isinstance(frame, (bytes, bytearray)) else self.encode(frame)
        if payload is None:
            return
        now = time.monotonic()
        with self.lock:
            self.frames.append((now, when or datetime.now(), payload))
            # Se descarta por antigüedad y por tamaño: el anillo nunca crece sin límite.
            horizon = now - self.seconds
            self.frames = [f for f in self.frames if f[0] >= horizon][-self.capacity:]

    def window(self, pre_seconds=None, post_seconds=None, reference=None):
        """Fotogramas alrededor de un instante. Devuelve lo que el anillo todavía conserva."""
        pre = config.VIDEO_PRE_EVENT_SECONDS if pre_seconds is None else pre_seconds
        post = config.VIDEO_POST_EVENT_SECONDS if post_seconds is None else post_seconds
        mark = reference if reference is not None else time.monotonic()
        with self.lock:
            return [f for f in self.frames if mark - pre <= f[0] <= mark + post]

    def latest(self):
        with self.lock:
            return self.frames[-1] if self.frames else None

    def clear(self):
        with self.lock:
            self.frames.clear()


class CameraStreamAdapter:
    """Interfaz común de una fuente de cámara.

    Una implementación real debe devolver fotogramas; una fuente no integrada devuelve None
    y lo declara en `unavailable_reason`, para que la interfaz diga «pendiente de integración»
    en lugar de aparentar que hubo una captura.
    """

    kind = 'abstract'

    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.ring = VideoRing()
        self.unavailable_reason = ''

    @property
    def active(self):
        return False

    def read(self):
        """Fotograma más reciente, o None cuando la fuente no entrega imagen."""
        return None

    def poll(self):
        frame = self.read()
        if frame is not None:
            self.ring.write(frame)
        return frame


class LiveWebcamAdapter(CameraStreamAdapter):
    """La webcam del equipo, ya gestionada por el módulo de reconocimiento en vivo.

    No abre la cámara por su cuenta: eso duplicaría el dispositivo, que en Windows es de uso
    exclusivo. Se apoya en la sesión existente y declara la fuente inactiva cuando no corre.
    """

    kind = 'webcam'

    @property
    def active(self):
        from services.live_recognition_service import running_for_camera
        return running_for_camera(self.camera_id) is not None

    def read(self):
        # Hay dos cámaras físicas: la de la laptop y la webcam USB. Cada una atiende a su
        # cámara de la red, así que se pregunta cuál está corriendo sobre ésta.
        from services.live_recognition_service import running_for_camera
        instance = running_for_camera(self.camera_id)
        if instance is None:
            self.unavailable_reason = ('La cámara del equipo no está entregando imagen en este momento. '
                                       'El fragmento de video queda pendiente de integración.')
            return None
        self.unavailable_reason = ''
        with instance._lock:
            frame = instance._frame
        return None if frame is None else frame.copy()


class SimulatedStreamAdapter(CameraStreamAdapter):
    """Fuente de demostración: la cámara existe y se considera activa, pero no entrega píxeles.

    Es deliberado que no invente una imagen. Los eventos de esas cámaras conservan audio,
    transcripción y contexto, y sus fotogramas quedan marcados como pendientes.
    """

    kind = 'simulated'

    @property
    def active(self):
        from services.cameras_service import get_camera
        camera = get_camera(self.camera_id)
        return bool(camera and camera.stream_status == 'CAMERA_STREAM_ACTIVE')

    def read(self):
        self.unavailable_reason = ('Cámara simulada: la fuente de video real está pendiente de '
                                   'integración. No se genera ninguna imagen sintética.')
        return None


ADAPTERS = {'webcam': LiveWebcamAdapter, 'simulated': SimulatedStreamAdapter}


class CameraMonitor:
    """Registro de fuentes activas. Único punto que conoce cómo llega la imagen."""

    def __init__(self):
        self._adapters = {}
        self._lock = threading.Lock()
        self._thread = None
        self._running = False
        # Una pausa la decide una persona y se respeta: el monitoreo no vuelve a abrir la
        # cámara por su cuenta hasta que alguien la reanude.
        self.paused_by = ''
        self.stream_error = ''
        self._device = None
        self._last_attempt = 0.0
        # El micrófono de la cámara es parte del mismo monitoreo continuo. Una sola sesión
        # compartida: el dispositivo es exclusivo y las páginas sólo la observan.
        self.audio_paused_by = ''
        self.audio_error = ''
        self._audio = None
        self._last_audio_attempt = 0.0

    def adapter(self, camera_id):
        from services.cameras_service import get_camera
        with self._lock:
            if camera_id not in self._adapters:
                camera = get_camera(camera_id)
                kind = (camera.stream_source if camera else 'simulated')
                self._adapters[camera_id] = ADAPTERS.get(kind, SimulatedStreamAdapter)(camera_id)
            return self._adapters[camera_id]

    def active_cameras(self):
        """Cámaras cuyo stream se considera activo, independientemente de la interfaz."""
        from services.cameras_service import get_cameras
        return [c for c in get_cameras() if c.stream_status == 'CAMERA_STREAM_ACTIVE']

    def describe(self, camera_id):
        adapter = self.adapter(camera_id)
        return {'camera_id': camera_id, 'kind': adapter.kind, 'active': adapter.active,
                'buffered_frames': len(adapter.ring.frames),
                'unavailable_reason': adapter.unavailable_reason}

    # ------------------------------------------------------------------ bucle continuo
    def start(self):
        """Arranca el consumo continuo. Idempotente: llamarlo dos veces no duplica el bucle.

        En las pruebas no se arranca: el bucle competiría por la cámara y el micrófono con
        las sesiones que ellas mismas manejan, y allí los anillos se llenan a propósito.
        """
        if self._running or not autostart_enabled():
            return self
        self._running = True
        self._thread = threading.Thread(target=self._loop, name='camera-monitor', daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._running = False

    @property
    def running(self):
        return self._running

    def _loop(self):
        while self._running:
            try:
                self.ensure_live_stream()
            except Exception as error:
                self.stream_error = str(error)
            try:
                self.ensure_audio_stream()
            except Exception as error:
                self.audio_error = str(error)
            for camera in self.active_cameras():
                try:
                    self.adapter(camera.id).poll()
                except Exception:
                    pass  # una fuente caída no puede detener el monitoreo de las demás
            time.sleep(config.CAMERA_STREAM_POLL_SECONDS)

    # ------------------------------------------------- la cámara del equipo, sin botones
    def ensure_live_stream(self):
        """Incorpora las cámaras del equipo al monitoreo continuo, sin intervención humana.

        El dispositivo lo resuelve el módulo en vivo por el tipo de cada ranura —la de la
        laptop y la webcam USB—, que además descarta las cámaras virtuales. Aquí no se
        duplica esa lógica: sólo se decide cuándo arrancar.
        """
        from services.live_recognition_service import LIVE_INSTANCES
        if not autostart_enabled() or self.paused_by:
            return False
        pending = [inst for inst in LIVE_INSTANCES if not inst.running]
        if not pending:
            return False
        now = time.monotonic()
        if now - self._last_attempt < config.CAMERA_AUTOSTART_RETRY_SECONDS:
            return False
        self._last_attempt = now
        started, problems = False, []
        for instance in pending:
            try:
                instance.start(actor='Sistema · monitoreo continuo')
                started = True
            except Exception as error:
                # Una cámara ausente u ocupada no es un fallo del servidor: se reintenta.
                problems.append(f'{instance.name}: {error}')
        self.stream_error = ' · '.join(problems)
        return started

    def pause_stream(self, actor='Sistema'):
        """Pausa deliberada. Las cámaras quedan libres y el monitoreo no las reabre solo."""
        from services.live_recognition_service import stop_all
        self.paused_by = actor
        stop_all(actor)
        store.audit(actor, 'Cámara', f'{actor} pausó la transmisión continua de las cámaras del equipo.',
                    camera_id=config.DEFAULT_CAMERA_ID, result='PAUSADA')

    def resume_stream(self, actor='Sistema'):
        from services.live_recognition_service import LIVE_INSTANCES
        self.paused_by = ''
        self._last_attempt = 0.0
        problems = []
        for instance in LIVE_INSTANCES:
            if instance.running:
                continue
            try:
                instance.start(actor=actor)
            except Exception as error:
                problems.append(f'{instance.name}: {error}')
        self.stream_error = ' · '.join(problems)
        store.audit(actor, 'Cámara', f'{actor} reanudó la transmisión continua de las cámaras del equipo.',
                    camera_id=config.DEFAULT_CAMERA_ID, result='RECONOCIENDO')
        if problems and all(not i.running for i in LIVE_INSTANCES):
            raise RuntimeError(self.stream_error)

    # -------------------------------------------------- el micrófono, también sin botones
    def audio_session(self):
        """Sesión de escucha compartida. Las páginas la observan; no crean la suya."""
        from services.monitoring_service import MonitoringSession
        with self._lock:
            if self._audio is None:
                self._audio = MonitoringSession(camera_id=config.DEFAULT_CAMERA_ID,
                                                actor='Sistema · monitoreo continuo')
            return self._audio

    def ensure_audio_stream(self):
        """Arranca la detección de auxilio sin que nadie la pida."""
        if not autostart_enabled() or self.audio_paused_by:
            return False
        session = self.audio_session()
        if session.running:
            return False
        now = time.monotonic()
        if now - self._last_audio_attempt < config.CAMERA_AUTOSTART_RETRY_SECONDS:
            return False
        self._last_audio_attempt = now
        try:
            session.start()
            self.audio_error = ''
            return True
        except Exception as error:
            self.audio_error = str(error)  # micrófono ocupado o ausente: se reintenta
            return False

    def pause_audio(self, actor='Sistema'):
        self.audio_paused_by = actor
        self.audio_session().stop()
        store.audit(actor, 'Voz', f'{actor} pausó la detección continua de auxilio en '
                                  f'{config.DEFAULT_CAMERA_ID}.',
                    camera_id=config.DEFAULT_CAMERA_ID, result='PAUSADA')

    def resume_audio(self, actor='Sistema', camera_id=None):
        session = self.audio_session()
        self.audio_paused_by = ''
        self._last_audio_attempt = 0.0
        if camera_id:
            session.camera_id = camera_id
        session.actor = actor
        session.start()
        self.audio_error = ''
        store.audit(actor, 'Voz', f'{actor} reanudó la detección continua de auxilio en '
                                  f'{session.camera_id}.',
                    camera_id=session.camera_id, result='ESCUCHANDO')

    def audio_state(self):
        session = self.audio_session()
        if session.running:
            return {'state': session.status, 'automatic': autostart_enabled() and not self.audio_paused_by,
                    'detail': ''}
        if self.audio_paused_by:
            return {'state': 'PAUSADA', 'automatic': False,
                    'detail': f'Pausada por {self.audio_paused_by}. El micrófono está libre.'}
        if not autostart_enabled():
            return {'state': 'DETENIDO', 'automatic': False,
                    'detail': 'El arranque automático está desactivado en este equipo.'}
        return {'state': 'CONECTANDO', 'automatic': True,
                'detail': self.audio_error or 'Incorporando el micrófono al monitoreo continuo…'}

    def stream_state(self):
        """Cómo está la cámara del equipo, para que la interfaz lo cuente sin adivinar."""
        from services.live_recognition_service import LIVE_INSTANCES
        running = [inst for inst in LIVE_INSTANCES if inst.running]
        if running:
            return {'state': 'EN VIVO', 'automatic': autostart_enabled() and not self.paused_by,
                    'detail': ' · '.join(inst.name for inst in running)}
        if self.paused_by:
            return {'state': 'PAUSADA', 'automatic': False,
                    'detail': f'Pausada por {self.paused_by}. La cámara está libre.'}
        if not autostart_enabled():
            return {'state': 'DETENIDA', 'automatic': False,
                    'detail': 'El arranque automático está desactivado en este equipo.'}
        return {'state': 'CONECTANDO', 'automatic': True,
                'detail': self.stream_error or 'Incorporando la cámara del equipo al monitoreo continuo…'}

    # ------------------------------------------------------- captura ligada a un evento
    def capture_event_evidence(self, event_id, camera_id, reference=None):
        """Conserva los fotogramas alrededor de un evento y los registra.

        Se piden varios instantes porque uno solo puede salir borroso, de perfil u ocluido.
        Cuando la fuente no entrega imagen, el fotograma se registra como pendiente de
        integración: queda constancia de que se intentó, sin fabricar una captura.
        """
        from services.event_frames_service import store_event_frames, write_event_clip
        adapter = self.adapter(camera_id)
        # `reference` es el instante del grito, no el momento en que se pide la evidencia:
        # cuando esto se llama ya pasaron los segundos posteriores que el audio esperó.
        mark = time.monotonic() if reference is None else reference
        window = adapter.ring.window(reference=mark)
        captures = []
        for offset in config.EVENT_FRAME_OFFSETS_SECONDS:
            frame = None
            when = datetime.now() + timedelta(seconds=offset)
            if window:
                target = mark + offset
                nearest = min(window, key=lambda f: abs(f[0] - target))
                if abs(nearest[0] - target) <= config.EVENT_FRAME_TOLERANCE_SECONDS:
                    frame, when = nearest[2], nearest[1]
            captures.append({'offset': offset, 'frame': frame, 'timestamp': when,
                             'reason': adapter.unavailable_reason if frame is None else ''})
        frames = store_event_frames(event_id, camera_id, captures)
        # El fragmento de video completo, no sólo los fotogramas sueltos: quien revise
        # necesita ver qué pasó antes y después, no una foto aislada.
        write_event_clip(event_id, camera_id, window)
        return frames


monitor = CameraMonitor()


def capture_event_evidence(event_id, camera_id, reference=None):
    """Punto único al que el detector de auxilio pide la evidencia visual de un evento.

    Un fallo aquí no puede tumbar la detección: el audio y la transcripción ya están a salvo,
    así que el problema se registra y el evento conserva lo que sí pudo obtenerse.
    """
    from services.event_frames_service import process_event_frames
    try:
        frames = monitor.capture_event_evidence(event_id, camera_id, reference)
        return frames, process_event_frames(event_id)
    except Exception as error:
        store.audit('Sistema', 'Evidencia',
                    f'No fue posible conservar evidencia visual de {event_id}: {error}',
                    camera_id=camera_id, result='PENDIENTE_INTEGRACION')
        return [], []
