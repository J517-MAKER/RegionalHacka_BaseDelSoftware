"""Shared voice pipeline: local microphone and manual input."""
import re
import threading
import unicodedata
from uuid import uuid4
from time import monotonic
import config
from models.voice_event import VoiceEvent
from services import store
from services.alerts_service import create_voice_alert
from services.users_service import require


def get_voice_events():
    prune_voice_history()
    return store.voice_events


def prune_voice_history():
    now = monotonic()
    store.voice_events[:] = [v for v in store.voice_events if v.expires_at is None or v.expires_at > now]
    # Keep alert-linked evidence, but bound the relevant non-alert demo history.
    linked = {a.voice_event_id for a in store.alerts}
    unlinked = [v for v in store.voice_events if v.id not in linked]
    overflow = {v.id for v in unlinked[config.VOICE_RELEVANT_HISTORY_LIMIT:]}
    store.voice_events[:] = [v for v in store.voice_events if v.id not in overflow]


def analyze_text(text, context=None, audio=None, timestamp=None):
    """Slow, UI-independent analysis. Caller supplies an isolated conversation."""
    from models.conversation_context import ConversationContext
    from services.context_analysis_service import analyze_conversation_context
    from services.audio_analysis_service import analyze_audio
    from services.risk_fusion_service import fuse_evidence
    context = context if context is not None else ConversationContext()
    previous = context.recent(timestamp)
    semantic = analyze_conversation_context([s.text for s in previous], text)
    acoustic = analyze_audio(audio, [s.rms_energy for s in previous])
    risk = fuse_evidence(semantic, acoustic)
    context.add(text, acoustic.rms_energy, timestamp)
    return risk, [s.text for s in previous]


def get_phrases():
    return list(store.phrases)


def set_phrases(text):
    actor = require('settings.manage')
    store.phrases[:] = list(dict.fromkeys(p.strip() for p in text.splitlines() if p.strip()))
    store.audit(actor, 'Configuración', 'Actualizó frases de auxilio')


def normalize(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if unicodedata.category(c) != 'Mn')
    return ' '.join(re.sub(r'[^a-z0-9\s]', ' ', text).split())


def classify_intent(text):
    """Distress detection only.

    Administrative spoken orders are not interpreted here: they belong exclusively to
    services/admin_voice_assistant_service.py, behind the administrator's permission.
    """
    normalized = normalize(text)
    result = {'intencion': 'SIN_COINCIDENCIA', 'subtipo': None, 'accion': None, 'parametros': {}}
    rules = [
        ('POSIBLE_SEGUIMIENTO', r'\b(?:me (?:estan|esta|vienen|viene) siguiendo|alguien me (?:sigue|viene siguiendo|esta siguiendo)|no me sigas)\b'),
        ('POSIBLE_AGRESION', r'\b(?:dejame|sueltame|alejate)\b'),
        ('SOLICITUD_AUTORIDAD', r'\b(?:llama|llamen|llame) a la policia\b'),
        ('AUXILIO_GENERAL', r'\b(?:ayuda|auxilio|ayudame)\b'),
    ]
    for subtype, pattern in rules:
        if re.search(pattern, normalized):
            return dict(result, intencion='SOLICITUD_AUXILIO', subtipo=subtype)
    if any(re.search(r'\b' + re.escape(normalize(p)) + r'\b', normalized) for p in store.phrases if normalize(p)):
        return dict(result, intencion='SOLICITUD_AUXILIO', subtipo='AUXILIO_GENERAL')
    return result


def process_text(text, camera_id=None, source='MICROPHONE', recognition_metadata=None,
                 assessment=None, context=None, audio=None, actor=None):
    """actor is supplied by the background monitor, authorised when the session started."""
    if actor is None:
        require('voice.monitor')
    camera_id = camera_id or config.DEFAULT_CAMERA_ID
    from services.cameras_service import get_camera
    camera = get_camera(camera_id)
    if not camera:
        raise ValueError('Selecciona una cámara de prueba válida.')
    if not text or not normalize(text):
        raise ValueError('No se detectó voz en la grabación o la frase está vacía.')
    parsed = classify_intent(text)
    event = VoiceEvent('VOICE-' + uuid4().hex[:12].upper(), store.now(), camera_id, text,
                       intent=parsed['intencion'], subtype=parsed['subtipo'], location=camera.location,
                       text_normalized=normalize(text), source=source, action=parsed['accion'],
                       parameters=parsed['parametros'], recognition_metadata=recognition_metadata or {})
    risk = assessment or analyze_text(text, context, audio)[0]
    event.assessment = risk
    event.classification, event.priority = risk.classification, risk.priority
    event.intent = 'SOLICITUD_AUXILIO' if risk.should_create_alert else 'SIN_COINCIDENCIA'
    event.subtype = parsed['subtipo'] if risk.should_create_alert else None
    if risk.should_create_alert and not event.subtype:
        event.subtype = 'AUXILIO_GENERAL'
    event.status = 'PENDIENTE_REVISION' if risk.should_create_alert else 'REQUIERE_MAS_CONTEXTO' if risk.classification == 'AMBIGUO' else 'SIN_ALERTA'
    if risk.classification == 'NORMAL':
        event.expires_at = monotonic() + config.CONTEXT_SECONDS
    store.voice_events.insert(0, event)
    if event.intent == 'SOLICITUD_AUXILIO':
        create_voice_alert(event)
        register_capture_in_database(event)
    elif risk.classification != 'NORMAL':
        # La conversación ordinaria no deja rastro en la bitácora: con la escucha continua serían
        # cientos de registros por hora, y lo que se dijo sin señales de auxilio se descarta.
        store.audit('Sistema', 'Voz', f'{event.id}: {event.classification}; prioridad {event.priority}', camera_id=camera_id, result=event.status)
    prune_voice_history()
    return event


_database_enabled = [True]


def database_reachable():
    """Fast probe: without it psycopg waits minutes when the container is not running."""
    import socket
    try:
        from services.db_service import DB_CONFIG
    except Exception:
        return False
    host = re.search(r'host=(\S+)', DB_CONFIG)
    port = re.search(r'port=(\d+)', DB_CONFIG)
    try:
        socket.create_connection((host[1] if host else 'localhost',
                                  int(port[1]) if port else 5432), timeout=.4).close()
        return True
    except OSError:
        return False


def register_capture_in_database(event):
    """Optional PostgreSQL persistence from the database module (docker-compose.yml).

    Sólo se guarda cuando hay un rostro real en cuadro: un vector inventado terminaría
    indistinguible de una huella real en las búsquedas por similitud de pgvector, y eso
    es fabricar evidencia. Sin rostro real, no se escribe nada en la base. La base es
    opcional: un controlador o contenedor ausente nunca debe interrumpir una detección.
    """
    if not _database_enabled[0]:
        return None
    if not database_reachable():
        _database_enabled[0] = False
        print('Base compartida (PostgreSQL) no disponible: el evento se conserva en la base local y en evidence/.')
        return None
    try:
        from services.db_service import guardar_captura_rostro
        from services.live_recognition_service import running_for_camera
        inst = running_for_camera(event.camera_id)
        face = inst.current_face(event.camera_id) if inst else None
        if not face:
            return None  # sin rostro real no se inventa un embedding
        captura = guardar_captura_rostro(codigo_camara=event.camera_id,
                                         embedding=face['embedding'].tolist(),
                                         ruta_foto=None,  # no se guarda ningún archivo en ese momento: no inventar la ruta
                                         tipo_evento=event.subtype or 'ALERTA_AUDIO')
    except Exception:
        captura = None
    if captura is None:
        # Sin contenedor ni controlador no se reintenta: la detección no puede esperar a la red.
        _database_enabled[0] = False
        print('Base compartida (PostgreSQL) no disponible: el evento se conserva en la base local y en evidence/.')
    return captura


def simulate_voice_event(text='ayuda, me están siguiendo', camera_id=None):
    return process_text(text, camera_id)


class VoiceError(ValueError):
    pass


class MicrophoneCapture:
    _device_lock = threading.Lock()

    def __init__(self):
        self.stream = None
        self.chunks = []
        self.samples = 0
        self.error = None
        self.full = False
        self.level = 0.0
        self.owns_device = False

    @staticmethod
    def available():
        try:
            import sounddevice as sd
            return sd.query_devices(kind='input')['max_input_channels'] > 0
        except Exception:
            return False

    def start(self):
        if not self._device_lock.acquire(blocking=False):
            raise VoiceError('El micrófono está ocupado por otra escucha.')
        self.owns_device = True
        self.chunks, self.samples, self.error, self.full = [], 0, None, False
        try:
            import sounddevice as sd
            import numpy as np
            def callback(data, frames, time, status):
                if status:
                    self.error = 'Se interrumpió la captura de audio. Revisa el dispositivo.'
                remaining = config.AUDIO_SAMPLE_RATE * config.AUDIO_MAX_SECONDS - self.samples
                if remaining > 0:
                    chunk = data[:remaining, 0].copy()
                    self.chunks.append(chunk)
                    self.samples += len(chunk)
                    self.level = min(1.0, float(np.sqrt(np.mean(chunk ** 2))) * 10)
                if self.samples >= config.AUDIO_SAMPLE_RATE * config.AUDIO_MAX_SECONDS:
                    self.full = True
                    raise sd.CallbackStop()
            self.stream = sd.InputStream(samplerate=config.AUDIO_SAMPLE_RATE, channels=1, dtype='float32', callback=callback)
            self.stream.start()
        except Exception as exc:
            self.close()
            raise VoiceError('No fue posible abrir el micrófono. Comprueba conexión, permisos de Windows e instalación de sounddevice.') from exc

    def close(self):
        try:
            if self.stream is not None:
                try:
                    self.stream.stop()
                finally:
                    self.stream.close()
        finally:
            self.stream = None
            if self.owns_device:
                self.owns_device = False
                self._device_lock.release()

    def stop(self):
        try:
            self.close()
        except Exception as exc:
            raise VoiceError('El dispositivo se desconectó durante la grabación.') from exc
        if self.error:
            raise VoiceError(self.error)
        if self.samples < config.AUDIO_SAMPLE_RATE // 2:
            raise VoiceError('Audio demasiado corto. Graba al menos medio segundo.')
        import numpy as np
        audio = np.concatenate(self.chunks)
        self.chunks = []
        if float(np.max(np.abs(audio))) < 0.0001:
            raise VoiceError('No se detectó voz en la grabación.')
        return audio


_model = None
_model_lock = threading.Lock()


def model_loaded():
    return _model is not None


def model_cached():
    """True si el modelo de voz ya está en la caché de Hugging Face: cargarlo no descarga nada."""
    import os
    from pathlib import Path
    cache = os.getenv('HF_HUB_CACHE') or Path(os.getenv('HF_HOME') or Path.home() / '.cache' / 'huggingface') / 'hub'
    return any(Path(cache).glob(f'models--Systran--faster-whisper-{config.VOICE_MODEL}/snapshots/*/model.bin'))


def transcribe_audio(audio):
    global _model
    with _model_lock:
        if _model is None:
            try:
                if config.VOICE_MODEL not in ('tiny', 'base', 'small'):
                    raise ValueError('Modelo no permitido')
                from faster_whisper import WhisperModel
                _model = WhisperModel(config.VOICE_MODEL, device='cpu', compute_type='int8')
            except Exception as exc:
                raise VoiceError('No fue posible cargar el modelo de reconocimiento. Puedes usar la pestaña Pruebas.') from exc
        try:
            segments, info = _model.transcribe(audio, language=config.VOICE_LANGUAGE, beam_size=1, vad_filter=True)
            segments = list(segments)
            text = ' '.join(s.text.strip() for s in segments).strip()
            if not text:
                raise VoiceError('No se detectó voz en la grabación.')
            return text, {'language': info.language, 'segments': [
                {'avg_logprob': s.avg_logprob, 'no_speech_prob': s.no_speech_prob,
                 'start': getattr(s, 'start', 0), 'end': getattr(s, 'end', 0),
                 'text': s.text.strip()} for s in segments]}
        except VoiceError:
            raise
        except Exception as exc:
            raise VoiceError('No fue posible transcribir el audio. Intenta nuevamente o utiliza Pruebas.') from exc


def warm_up():
    """Carga el modelo antes de que llegue la primera frase.

    La carga cuesta varios segundos y ocurría dentro de la primera ventana analizada, así
    que el arranque de la escucha se comía justo lo que alguien dijera al principio.
    """
    import numpy as np
    try:
        transcribe_audio(np.zeros(config.AUDIO_SAMPLE_RATE, dtype='float32'))
    except VoiceError:
        pass  # silencio: sólo interesa que el modelo quede en memoria
    return _model is not None


def transcribe_window(audio, start, previous_end):
    """Drop segments wholly contained in a previously processed overlap."""
    text, metadata = transcribe_audio(audio)
    segments = [s for s in metadata['segments'] if start + s['end'] > previous_end + .05]
    metadata['segments'] = segments
    return ' '.join(s['text'] for s in segments), metadata
