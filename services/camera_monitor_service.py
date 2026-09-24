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
from services.video_ring import VideoRing  # noqa: F401  (se reexporta: otros módulos lo importan de aquí)


def autostart_enabled():
    """La cámara del equipo se enciende sola con el servidor.

    Se desactiva durante las pruebas: abrir la webcam real en mitad de una prueba pelearía
    con las sesiones que ellas mismas arrancan, y el dispositivo es de uso exclusivo.
    """
    return config.CAMERA_AUTOSTART and 'PYTEST_CURRENT_TEST' not in os.environ


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
    def ring(self):
        """El anillo lo llena el propio hilo de captura de la ranura que transmite esta cámara,
        con la marca de tiempo exacta de cada cuadro. Sin transmisión, un anillo vacío."""
        from services.live_recognition_service import running_for_camera
        instance = running_for_camera(self.camera_id)
        return instance.ring if instance is not None else self._idle_ring

    @ring.setter
    def ring(self, value):
        self._idle_ring = value

    @property
    def active(self):
        from services.live_recognition_service import running_for_camera
        return running_for_camera(self.camera_id) is not None

    def poll(self):
        # El hilo de captura ya escribe en el anillo; volver a escribir aquí duplicaría cuadros.
        self.read()
        return None

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
        # Una cámara pausada a mano desde la página en vivo se respeta hasta que la inicien.
        pending = [inst for inst in LIVE_INSTANCES if not inst.running and not inst.paused_by]
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
            instance.paused_by = ''
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
    def evidence_camera(self, camera_id):
        """Cámara de la que se toma el video de un evento.

        Es la asociada al micrófono. Si en ese momento no transmite —una computadora sin
        cámara integrada, o una cámara pausada— se usa otra cámara del equipo que sí esté en
        vivo: un video de la misma sala es mejor evidencia que ninguno.
        """
        from services.live_recognition_service import LIVE_INSTANCES, running_for_camera
        if running_for_camera(camera_id) is not None:
            return camera_id
        live = [inst for inst in LIVE_INSTANCES if inst.running]
        return live[0].camera_id if live else camera_id

    @staticmethod
    def _wait_for_post_roll(ring, mark):
        """Espera a que el anillo tenga los segundos posteriores al evento, con un límite."""
        if ring.latest() is None:
            return
        target = mark + config.VIDEO_POST_EVENT_SECONDS - .25
        deadline = time.monotonic() + config.VIDEO_POST_EVENT_SECONDS + 2
        while time.monotonic() < deadline:
            latest = ring.latest()
            if latest is None or latest[0] >= target:
                return
            time.sleep(.1)

    def capture_event_evidence(self, event_id, camera_id, reference=None, audio=None):
        """Conserva el clip (video con audio) y las fotos alrededor de un evento.

        El clip abarca VIDEO_PRE_EVENT_SECONDS antes y VIDEO_POST_EVENT_SECONDS después del
        instante de la frase. Las fotos se piden en varios instantes porque una sola puede
        salir borrosa, de perfil u ocluida. Cuando la fuente no entrega imagen, cada foto se
        registra como pendiente de integración: queda constancia de que se intentó, sin
        fabricar una captura.
        """
        from services.event_frames_service import store_event_frames, write_event_clip
        from services.live_recognition_service import LIVE_INSTANCES
        # `reference` es el instante de la frase, no el momento en que se pide la evidencia:
        # cuando esto se llama ya pasaron los segundos posteriores que el audio esperó.
        mark = time.monotonic() if reference is None else reference
        mark_wall = datetime.now() - timedelta(seconds=time.monotonic() - mark)
        source = self.evidence_camera(camera_id)
        adapter = self.adapter(source)
        ring = adapter.ring
        self._wait_for_post_roll(ring, mark)
        window = ring.window(reference=mark)
        captures = []
        for offset in config.EVENT_FRAME_OFFSETS_SECONDS:
            frame, when = None, mark_wall + timedelta(seconds=offset)
            if window:
                target = mark + offset
                nearest = min(window, key=lambda f: abs(f[0] - target))
                if abs(nearest[0] - target) <= config.EVENT_FRAME_TOLERANCE_SECONDS:
                    frame, when = nearest[2], nearest[1]
            captures.append({'offset': offset, 'frame': frame, 'timestamp': when,
                             'reason': adapter.unavailable_reason if frame is None else ''})
        frames = store_event_frames(event_id, source, captures)
        # El fragmento completo, no sólo fotos sueltas: quien revise necesita ver y oír qué
        # pasó antes y después de la frase.
        write_event_clip(event_id, source, window, audio=audio, reference=mark)
        # Otros ángulos del mismo instante, si hay más cámaras del equipo transmitiendo.
        for instance in LIVE_INSTANCES:
            if instance.running and instance.camera_id != source:
                other = instance.ring.window(reference=mark)
                if other:
                    write_event_clip(event_id, instance.camera_id, other, audio=audio, reference=mark,
                                     angle=True)
        return frames


monitor = CameraMonitor()


def capture_event_evidence(event_id, camera_id, reference=None, audio=None):
    """Punto único al que el detector de auxilio pide la evidencia visual de un evento.

    `audio` es el mismo fragmento que se guardó como WAV ({'samples', 'rate', 'start_mono'}):
    se incorpora al clip para que el video se escuche sincronizado.

    Un fallo aquí no puede tumbar la detección: el audio y la transcripción ya están a salvo,
    así que el problema se registra y el evento conserva lo que sí pudo obtenerse.
    """
    from services.event_frames_service import process_event_frames
    try:
        frames = monitor.capture_event_evidence(event_id, camera_id, reference, audio)
        return frames, process_event_frames(event_id)
    except Exception as error:
        store.audit('Sistema', 'Evidencia',
                    f'No fue posible conservar evidencia visual de {event_id}: {error}',
                    camera_id=camera_id, result='PENDIENTE_INTEGRACION')
        return [], []
