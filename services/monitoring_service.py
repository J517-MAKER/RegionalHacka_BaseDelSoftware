"""Continuous listening: microphone -> ring buffer -> transcription -> context -> evidence.

The operator never types anything: every event comes from real audio. Ordinary
conversation stays in the circular buffer and is overwritten; only a possible
request for help is written to disk, together with its surrounding seconds.
"""
import threading
from datetime import datetime, timedelta
from time import sleep
import config
from models.conversation_context import ConversationContext
from services.audio_buffer import AudioRing
from services.voice_service import (MicrophoneCapture, VoiceError, analyze_text, process_text,
                                    transcribe_window)


def microphone_available():
    return MicrophoneCapture.available()


class MonitoringSession:
    """One console, one microphone. Results are polled by the interface."""

    def __init__(self, camera_id=None, actor='Sistema'):
        self.camera_id = camera_id or config.DEFAULT_CAMERA_ID
        self.actor = actor
        self.ring = AudioRing()
        self.context = ConversationContext()
        self.results = []
        self.status = 'DETENIDO'
        self.error = None
        self.level = 0.0
        self.running = False
        self.started_wall = None
        self.stream = None
        self.worker = None
        self._stop = threading.Event()
        self._owns_device = False

    # ------------------------------------------------------------------ capture
    def start(self):
        if self.running:
            return
        if not MicrophoneCapture._device_lock.acquire(blocking=False):
            raise VoiceError('El micrófono está ocupado por otra escucha.')
        self._owns_device = True
        self._stop.clear()
        self.ring.clear()
        self.context.clear()
        self.error = None
        self.started_wall = datetime.now()
        try:
            import numpy as np
            import sounddevice as sd

            def callback(data, frames, time, status):
                if status:
                    self.error = 'Se interrumpió la captura de audio. Revisa el dispositivo.'
                chunk = data[:, 0].copy()
                self.ring.write(chunk)
                self.level = min(1.0, float(np.sqrt(np.mean(chunk ** 2))) * 10)

            self.stream = sd.InputStream(samplerate=config.AUDIO_SAMPLE_RATE, channels=1,
                                         dtype='float32', callback=callback)
            self.stream.start()
        except Exception as exc:
            self._release()
            raise VoiceError('No fue posible abrir el micrófono. Comprueba conexión, permisos de Windows '
                             'e instalación de sounddevice.') from exc
        self.running = True
        self.status = 'ESCUCHANDO'
        self.worker = threading.Thread(target=self._loop, name='voice-monitor', daemon=True)
        self.worker.start()

    def stop(self):
        self._stop.set()
        self.running = False
        worker, self.worker = self.worker, None
        self._release()
        if worker and worker is not threading.current_thread():
            worker.join(timeout=5)
        # Ordinary conversation never outlives the session.
        self.ring.clear()
        self.context.clear()
        self.level = 0.0
        self.status = 'DETENIDO'

    def _release(self):
        stream, self.stream = self.stream, None
        try:
            if stream is not None:
                try:
                    stream.stop()
                finally:
                    stream.close()
        except Exception:
            pass
        finally:
            if self._owns_device:
                self._owns_device = False
                MicrophoneCapture._device_lock.release()

    # ------------------------------------------------------------------ pipeline
    def _timestamp(self, sample):
        return (self.started_wall + timedelta(seconds=sample / config.AUDIO_SAMPLE_RATE)).strftime('%Y-%m-%d %H:%M:%S')

    def _wait_for(self, sample):
        while not self._stop.is_set() and self.ring.written < sample:
            sleep(.15)
        return not self._stop.is_set()

    def _loop(self):
        rate = config.AUDIO_SAMPLE_RATE
        window = int(config.AUDIO_WINDOW_SECONDS * rate)
        hop = max(1, int((config.AUDIO_WINDOW_SECONDS - config.AUDIO_OVERLAP_SECONDS) * rate))
        start, previous_end = 0, -1.0
        while not self._stop.is_set():
            end = start + window
            if not self._wait_for(end):
                break
            try:
                start = self._analyze(start, end, previous_end)
            except Exception as exc:  # a single bad window must not stop the service
                self.error = str(exc) if isinstance(exc, (VoiceError, ValueError, PermissionError)) else \
                    'No fue posible analizar el último fragmento de audio.'
                start = start + hop
            else:
                previous_end = end / rate
        self.status = 'DETENIDO'

    def _analyze(self, start, end, previous_end):
        """Returns the next absolute start sample."""
        rate = config.AUDIO_SAMPLE_RATE
        hop = max(1, int((config.AUDIO_WINDOW_SECONDS - config.AUDIO_OVERLAP_SECONDS) * rate))
        samples = self.ring.read(start, end)
        self.status = 'ANALIZANDO'
        try:
            text, metadata = transcribe_window(samples, start / rate, previous_end)
        except VoiceError as exc:
            if 'No se detectó voz' in str(exc):
                self.status = 'ESCUCHANDO'
                return start + hop
            raise
        if not text.strip():
            self.status = 'ESCUCHANDO'
            return start + hop
        risk, previous = analyze_text(text, self.context, samples)
        clip, clip_start, clip_end, faces = None, start, end, []
        if risk.should_create_alert:
            # Who is in view right now, before waiting for the seconds after the request.
            from services.live_recognition_service import live
            faces = live.snapshot_faces(self.camera_id)
            # Keep the seconds before and after the possible request for help.
            self.status = 'CONSERVANDO EVIDENCIA'
            clip_start = max(0, start - int(config.EVIDENCE_PRE_SECONDS * rate))
            clip_end = end + int(config.EVIDENCE_POST_SECONDS * rate)
            self._wait_for(clip_end)
            clip = self.ring.read(clip_start, clip_end)
            clip_end = clip_start + len(clip)
        event = process_text(text, self.camera_id, 'MICROPHONE', metadata, assessment=risk,
                             actor=self.actor)
        evidence = None
        if clip is not None and len(clip):
            from services.evidence_service import create_evidence
            evidence = create_evidence(event, risk, clip, self._timestamp(clip_start),
                                       self._timestamp(clip_end), actor=self.actor)
            from services.live_recognition_service import LiveRecognition
            LiveRecognition.attach_faces_to_evidence(evidence, faces)
        self.results.insert(0, self._summary(event, risk, evidence, previous))
        del self.results[12:]
        self.status = 'ESCUCHANDO'
        return (clip_end if clip is not None else start + hop)

    def _summary(self, event, risk, evidence, previous):
        """Operator-facing summary only: no JSON, objects or internal names."""
        semantic, acoustic = risk.semantic_analysis, risk.acoustic_summary
        signals = list(semantic.signals)
        if acoustic.available:
            signals.append('Cambio acústico significativo' if acoustic.abrupt_change else 'Variación acústica moderada')
        readable = {'NORMAL': 'Conversación sin señales de auxilio',
                    'AMBIGUO': 'Señales insuficientes; requiere más contexto',
                    'POSIBLE_AUXILIO': 'Posible solicitud de auxilio',
                    'ALTA_PRIORIDAD': 'Posible solicitud de auxilio con varias señales'}
        if evidence:
            outcome = (f'Evento {evidence.event_id} creado.\nAudio protegido correctamente '
                       f'({evidence.audio_duration:.0f} s).\nPendiente de revisión.')
        elif risk.classification == 'AMBIGUO':
            outcome = 'Sin evento. Se requiere más contexto; el audio no se conserva.'
        else:
            outcome = 'Sin evento. El audio y la transcripción se descartan.'
        return {'time': event.timestamp, 'camera': event.camera_id, 'transcript': event.text_original,
                'classification': risk.classification, 'headline': readable.get(risk.classification, risk.classification),
                'priority': risk.priority, 'signals': signals or ['Sin señales relevantes'],
                'outcome': outcome, 'event_id': evidence.event_id if evidence else None,
                'context': previous, 'analysis_mode': semantic.mode, 'state': event.status}
