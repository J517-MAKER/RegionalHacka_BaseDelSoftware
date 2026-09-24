"""Modelos de reconocimiento listos sin que nadie ejecute nada.

Al arrancar NEXO se preparan en segundo plano el modelo facial (InsightFace) y el de voz
(faster-whisper). La primera vez se descargan solos —necesitan internet— y después sólo se
cargan. Si algo falla, por ejemplo sin conexión, se reintenta solo cada minuto. El encabezado y
las páginas consultan `setup` para decir en palabras simples qué está pasando.
"""
import logging
import os
import threading

import config

logger = logging.getLogger(__name__)

# Estados de cada modelo: PENDIENTE · DESCARGANDO · CARGANDO · LISTO · ERROR · DESACTIVADO
WORKING = ('DESCARGANDO', 'CARGANDO')


def enabled():
    """Nunca bajo las pruebas: descargarían cientos de MB."""
    return config.MODELS_AUTOPREPARE and 'PYTEST_CURRENT_TEST' not in os.environ


class ModelSetup:
    def __init__(self):
        self.face, self.face_error = 'PENDIENTE', ''
        self.voice, self.voice_error = 'PENDIENTE', ''
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if not enabled() or (self._thread and self._thread.is_alive()):
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,), name='model-setup', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self, stop):
        while not stop.is_set():
            face, voice = self.prepare_face(), self.prepare_voice()
            if face and voice:
                return
            stop.wait(config.FACE_MODEL_RETRY_SECONDS)

    # Cada preparación devuelve True cuando ya no hay nada que reintentar.
    def prepare_face(self):
        from services import face_engine
        if face_engine.loaded():
            self.face, self.face_error = 'LISTO', ''
            return True
        if not face_engine.installed():
            self.face, self.face_error = 'ERROR', 'InsightFace no está instalado: ejecuta iniciar.ps1.'
            return True
        if not face_engine.model_downloaded() and not config.FACE_AUTO_DOWNLOAD:
            self.face, self.face_error = 'DESACTIVADO', 'Descarga automática desactivada (FACE_AUTO_DOWNLOAD=false).'
            return True
        self.face = 'CARGANDO' if face_engine.model_downloaded() else 'DESCARGANDO'
        try:
            face_engine.load()
        except face_engine.FaceEngineUnavailable as error:
            self.face, self.face_error = 'ERROR', str(error)
            logger.warning('Modelo facial: %s', error)
            return False
        self.face, self.face_error = 'LISTO', ''
        return True

    def prepare_voice(self):
        from services import voice_service
        if voice_service.model_loaded():
            self.voice, self.voice_error = 'LISTO', ''
            return True
        self.voice = 'CARGANDO' if voice_service.model_cached() else 'DESCARGANDO'
        if voice_service.warm_up():
            self.voice, self.voice_error = 'LISTO', ''
            return True
        self.voice, self.voice_error = 'ERROR', ('No se pudo descargar el modelo de voz. Revisa la conexión a '
                                                 'internet; NEXO lo vuelve a intentar solo.')
        logger.warning('Modelo de voz: %s', self.voice_error)
        return False

    def notice(self):
        """(texto breve, detalle) para el encabezado mientras algo se prepara o falló; None si todo está listo."""
        from services import face_engine
        if self.face == 'DESCARGANDO':
            downloaded = face_engine.download_progress()
            return ('DESCARGANDO RECONOCIMIENTO FACIAL' + (f' · {downloaded:.0f} MB' if downloaded else ''),
                    'Primera vez: el modelo facial (unos 280 MB) se descarga solo. La cámara ya graba.')
        if self.face == 'CARGANDO':
            return 'PREPARANDO RECONOCIMIENTO FACIAL', 'Cargando el modelo facial.'
        if self.voice == 'DESCARGANDO':
            return ('DESCARGANDO DETECCIÓN POR VOZ',
                    'Primera vez: el modelo de voz (unos 145 MB) se descarga solo.')
        if self.voice == 'CARGANDO':
            return 'PREPARANDO DETECCIÓN POR VOZ', 'Cargando el modelo de voz.'
        errors = [text for state, text in ((self.face, self.face_error), (self.voice, self.voice_error))
                  if state == 'ERROR' and text]
        if errors:
            return 'MODELOS SIN DESCARGAR · SE REINTENTA SOLO', ' '.join(errors)
        return None


setup = ModelSetup()
