"""Continuous listening: microphone -> ring buffer -> transcription -> context -> evidence.

The operator never types anything: every event comes from real audio. Ordinary
conversation stays in the circular buffer and is overwritten; only a possible
request for help is written to disk, together with its surrounding seconds.
"""
import threading
from datetime import datetime, timedelta
from time import monotonic, sleep
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
        # (muestras escritas, reloj monotónico, fecha y hora) al llegar el último bloque del
        # micrófono. Ubica en el tiempo cualquier muestra reciente sin acumular deriva entre el
        # reloj de la tarjeta de sonido y el del sistema, y alinea el audio con las cámaras.
        self._anchor = None

    # ------------------------------------------------------------------ capture
    def start(self):
        if self.running:
            return
        if not MicrophoneCapture._device_lock.acquire(blocking=False):
            raise VoiceError('El micrófono está ocupado por otra escucha.')
        self._owns_device = True
        # Una señal de alto por sesión: si el análisis anterior sigue en una transcripción larga
        # (la primera vez, descargando el modelo de voz), no revive junto a la nueva escucha.
        self._stop = threading.Event()
        self.ring.clear()
        self.context.clear()
        self.error = None
        self.started_wall = datetime.now()
        self._anchor = None
        try:
            import numpy as np
            import sounddevice as sd

            def callback(data, frames, time_info, status):
                if status:
                    self.error = 'Se interrumpió la captura de audio. Revisa el dispositivo.'
                chunk = data[:, 0].copy()
                written = self.ring.write(chunk)
                self._anchor = (written, monotonic(), datetime.now())
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
        # El modelo tarda segundos en cargar. Se precarga aparte para que esa espera no se
        # coma justo lo que alguien diga en los primeros instantes de la escucha.
        threading.Thread(target=self._warm_up, name='voice-warmup', daemon=True).start()
        self.worker = threading.Thread(target=self._loop, args=(self._stop,), name='voice-monitor', daemon=True)
        self.worker.start()

    def _warm_up(self):
        from services.voice_service import warm_up
        try:
            warm_up()
        except Exception:
            pass  # si falla, la primera ventana lo intentará de nuevo

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
    def sample_clock(self, sample):
        """(reloj monotónico, fecha y hora) de una muestra absoluta del anillo.

        Con micrófono real se calcula desde el último bloque recibido; sin él (pruebas), desde
        el inicio de la sesión, y el monotónico queda en None porque no hay cámara que alinear.
        """
        anchor = self._anchor
        if anchor:
            written, mono, wall = anchor
            delta = (written - sample) / config.AUDIO_SAMPLE_RATE
            return mono - delta, wall - timedelta(seconds=delta)
        started = self.started_wall or datetime.now()
        return None, started + timedelta(seconds=sample / config.AUDIO_SAMPLE_RATE)

    def _timestamp(self, sample):
        return self.sample_clock(sample)[1].strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def trigger_offset(metadata):
        """Segundos desde el inicio de la ventana hasta la frase de auxilio.

        Whisper entrega cada segmento con su propio inicio. Se toma el primero que ya suena a
        petición de ayuda por sí solo; si ninguno lo hace aislado (lo decidió el contexto), el
        primero con voz. Así el clip queda centrado en la frase y no en el borde de la ventana.
        """
        from services.voice_service import classify_intent
        segments = (metadata or {}).get('segments') or []
        for segment in segments:
            if classify_intent(segment.get('text') or '')['intencion'] == 'SOLICITUD_AUXILIO':
                return max(0.0, float(segment.get('start') or 0))
        return max(0.0, float(segments[0].get('start') or 0)) if segments else 0.0

    def _wait_for(self, sample, stop=None):
        stop = self._stop if stop is None else stop
        while not stop.is_set() and self.ring.written < sample:
            sleep(.15)
        return not stop.is_set()

    def _loop(self, stop=None):
        stop = self._stop if stop is None else stop
        rate = config.AUDIO_SAMPLE_RATE
        window = int(config.AUDIO_WINDOW_SECONDS * rate)
        hop = max(1, int((config.AUDIO_WINDOW_SECONDS - config.AUDIO_OVERLAP_SECONDS) * rate))
        start, previous_end = 0, -1.0
        max_lag = int(config.AUDIO_MAX_LAG_SECONDS * rate)
        while not stop.is_set():
            end = start + window
            if not self._wait_for(end, stop):
                break
            # Si el análisis se quedó atrás —una transcripción lenta, la espera de evidencia—
            # se salta al presente. Arrastrar el retraso haría que la escucha respondiera
            # siempre a lo que se dijo hace medio minuto, y el anillo acabaría descartando
            # esas muestras de todos modos.
            if self.ring.written - end > max_lag:
                start = max(self.ring.oldest(), self.ring.written - window)
                end, previous_end = start + window, -1.0
            try:
                start = self._analyze(start, end, previous_end, stop)
            except Exception as exc:  # a single bad window must not stop the service
                self.error = str(exc) if isinstance(exc, (VoiceError, ValueError, PermissionError)) else \
                    'No fue posible analizar el último fragmento de audio.'
                start = start + hop
            else:
                previous_end = end / rate
        if stop is self._stop:  # un análisis rezagado no apaga la escucha que ya se reanudó
            self.status = 'DETENIDO'

    def _analyze(self, start, end, previous_end, stop=None):
        """Returns the next absolute start sample."""
        stop = self._stop if stop is None else stop
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
        event_mark, trigger = None, start
        if risk.should_create_alert:
            # Instante real de la frase dentro de la ventana, no el del final del análisis: la
            # transcripción llega segundos después y el clip saldría descentrado.
            trigger = start + int(self.trigger_offset(metadata) * rate)
            event_mark = self.sample_clock(trigger)[0]
            if event_mark is None:  # sin micrófono real: se estima respecto del presente
                event_mark = monotonic() - (self.ring.written - trigger) / rate
            # Who is in view right now, before waiting for the seconds after the request.
            from services.live_recognition_service import running_for_camera
            inst = running_for_camera(self.camera_id)
            faces = inst.snapshot_faces(self.camera_id) if inst else []
            # Keep the seconds before and after the possible request for help.
            self.status = 'CONSERVANDO EVIDENCIA'
            clip_start = max(self.ring.oldest(), trigger - int(config.EVIDENCE_PRE_SECONDS * rate))
            clip_end = trigger + int(config.EVIDENCE_POST_SECONDS * rate)
            self._wait_for(clip_end, stop)
            if stop is self._stop:
                # Con mucho retraso en el análisis, el principio pudo descartarse mientras se
                # esperaba: el clip empieza donde de verdad empieza lo leído.
                clip_start, clip = self.ring.read_span(clip_start, clip_end)
                clip_end = clip_start + len(clip)
            # Si no, la escucha se reinició mientras se transcribía: el anillo ya es de otra
            # sesión y ese audio no es de este evento. El evento queda registrado, sin clip.
        event = process_text(text, self.camera_id, 'MICROPHONE', metadata, assessment=risk,
                             actor=self.actor)
        evidence = None
        if clip is not None and len(clip):
            from services.evidence_service import create_evidence
            evidence = create_evidence(event, risk, clip, self._timestamp(clip_start),
                                       self._timestamp(clip_end), actor=self.actor,
                                       trigger_timestamp=self._timestamp(trigger))
            from services.live_recognition_service import LiveRecognition
            LiveRecognition.attach_faces_to_evidence(evidence, faces)
            # Un solo event_id relaciona audio, video, fotos y personas candidatas. La captura
            # es automática: el operador no tiene que pedir una fotografía ni un video.
            from services.camera_monitor_service import capture_event_evidence
            audio_start = self.sample_clock(clip_start)[0]
            if audio_start is None:
                audio_start = event_mark - (trigger - clip_start) / rate
            capture_event_evidence(evidence.event_id, self.camera_id, reference=event_mark,
                                   audio={'samples': clip, 'rate': rate, 'start_mono': audio_start})
        self.results.insert(0, self._summary(event, risk, evidence, previous))
        del self.results[12:]
        self.status = 'ESCUCHANDO'
        # Tras un evento se sigue después de la ventana completa: si el clip terminó antes, la
        # misma frase no debe volver a analizarse y crear un segundo evento.
        return max(clip_end, end) if clip is not None else start + hop

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
            if evidence.video_status == 'ATTACHED':
                video = (f'Video{" con audio" if evidence.video_has_audio else ""} de '
                         f'{evidence.video_camera_id} conservado ({config.EVIDENCE_PRE_SECONDS} s antes y '
                         f'{config.EVIDENCE_POST_SECONDS} s después de la frase).')
            else:
                video = 'Video pendiente: ninguna cámara del equipo entregaba imagen en ese momento.'
            outcome = (f'Evento {evidence.event_id} creado.\nAudio protegido correctamente '
                       f'({evidence.audio_duration:.0f} s).\n{video}\nPendiente de revisión.')
        elif risk.classification == 'AMBIGUO':
            outcome = 'Sin evento. Se requiere más contexto; el audio no se conserva.'
        else:
            outcome = 'Sin evento. El audio y la transcripción se descartan.'
        return {'time': event.timestamp, 'camera': event.camera_id, 'transcript': event.text_original,
                'classification': risk.classification, 'headline': readable.get(risk.classification, risk.classification),
                'priority': risk.priority, 'signals': signals or ['Sin señales relevantes'],
                'outcome': outcome, 'event_id': evidence.event_id if evidence else None,
                'context': previous, 'analysis_mode': semantic.mode, 'state': event.status}
