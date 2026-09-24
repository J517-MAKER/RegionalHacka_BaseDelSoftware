"""Evidencia automática de una posible solicitud de auxilio: video + audio + fotos.

La cámara y el micrófono están siempre encendidos. Cuando alguien dice «ayuda» (u otra frase
de auxilio), el sistema conserva por sí solo un clip de EVIDENCE_PRE_SECONDS antes y
EVIDENCE_POST_SECONDS después de la frase, con el audio sincronizado, y varias fotos, para que
una persona pueda comprobar qué pasó. Estas pruebas recorren ese camino con cuadros y audio
sintéticos: no hace falta cámara, micrófono ni modelos.
"""
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np

import config
from services import store
from services.evidence_service import verify_integrity, verify_video_integrity
from services.live_recognition_service import live_1, live_2
from services.monitoring_service import MonitoringSession

RATE = config.AUDIO_SAMPLE_RATE


def tone(seconds, amplitude=.2):
    t = np.arange(int(seconds * RATE), dtype=np.float32) / RATE
    return (np.sin(2 * np.pi * 220 * t) * amplitude).astype(np.float32)


def fill_ring(instance, camera_id, now, seconds=25):
    """Una ranura «en vivo» con los últimos segundos de video en su anillo."""
    from services.video_ring import VideoRing
    instance.running, instance.camera_id = True, camera_id
    instance.ring.clear()
    frames = int(seconds * config.VIDEO_RING_FPS)
    for index in range(frames + 1):
        moment = now - seconds + index / config.VIDEO_RING_FPS
        image = np.full((240, 320, 3), (index * 3) % 255, dtype=np.uint8)
        instance.ring.write(VideoRing.encode(image), when=datetime.now() - timedelta(seconds=now - moment),
                            at=moment)


class EventEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = (store.voice_events[:], store.alerts[:], store.logs[:], store.evidence[:],
                         store.event_frames[:], store.person_candidates[:])
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.patches = [patch('config.AI_CONTEXT_ENABLED', False),
                        patch('config.EVIDENCE_DIR', root),
                        patch('config.EVIDENCE_AUDIO_DIR', root / 'audio'),
                        patch('config.EVIDENCE_VIDEO_DIR', root / 'video')]
        for item in self.patches:
            item.start()
        self.addCleanup(self.restore)

    def restore(self):
        for item in reversed(self.patches):
            item.stop()
        for instance in (live_1, live_2):
            instance.running = False
            instance.ring.clear()
        live_1.camera_id, live_2.camera_id = config.DEFAULT_CAMERA_ID, config.SECOND_CAMERA_ID
        (store.voice_events[:], store.alerts[:], store.logs[:], store.evidence[:],
         store.event_frames[:], store.person_candidates[:]) = self.snapshot

    RECORDED, WINDOW_START = 20, 8

    def shout(self, phrase_start=2.0, phrase='por favor déjame, necesito ayuda'):
        """20 s de audio «en vivo»; la ventana analizada va del segundo 8 al 14 y la frase de
        auxilio empieza `phrase_start` segundos dentro de ella."""
        session = MonitoringSession(camera_id=config.DEFAULT_CAMERA_ID, actor='Operador01')
        session.started_wall = datetime.now() - timedelta(seconds=self.RECORDED)
        session.ring.write(tone(self.RECORDED))
        now_mono, now_wall = time.monotonic(), datetime.now()
        session._anchor = (session.ring.written, now_mono, now_wall)
        start, window = self.WINDOW_START * RATE, int(config.AUDIO_WINDOW_SECONDS * RATE)
        segments = [{'text': 'vamos a la cafetería', 'start': 0.0, 'end': .2},
                    {'text': phrase, 'start': phrase_start, 'end': phrase_start + 2}]
        with patch('services.monitoring_service.transcribe_window',
                   return_value=(' '.join(s['text'] for s in segments), {'segments': segments})):
            following = session._analyze(start, start + window, -1.0)
        trigger_wall = now_wall - timedelta(seconds=self.RECORDED - (self.WINDOW_START + phrase_start))
        return session, following, trigger_wall, now_mono

    def test_clip_is_centered_on_the_phrase_with_audio_inside(self):
        import av
        now = time.monotonic()
        fill_ring(live_1, config.DEFAULT_CAMERA_ID, now)
        session, following, trigger_wall, _ = self.shout()
        evidence = store.evidence[0]

        # 5 s antes y 5 s después de la frase, en audio...
        self.assertAlmostEqual(evidence.audio_duration,
                               config.EVIDENCE_PRE_SECONDS + config.EVIDENCE_POST_SECONDS, delta=.2)
        self.assertEqual(evidence.trigger_timestamp, trigger_wall.strftime('%Y-%m-%d %H:%M:%S'))
        self.assertTrue(verify_integrity(evidence))
        # ...y en video, con el mismo audio adentro.
        self.assertEqual(evidence.video_status, 'ATTACHED')
        self.assertTrue(evidence.video_has_audio)
        self.assertEqual(evidence.video_camera_id, config.DEFAULT_CAMERA_ID)
        self.assertTrue(verify_video_integrity(evidence))
        path = config.BASE_DIR / evidence.video_file
        with av.open(str(path)) as container:
            video, audio = container.streams.video[0], container.streams.audio[0]
            self.assertEqual(video.codec_context.name, 'h264')
            self.assertEqual(audio.codec_context.name, 'aac')
            decoded = [frame.time for frame in container.decode(video=0)]
        expected = config.VIDEO_PRE_EVENT_SECONDS + config.VIDEO_POST_EVENT_SECONDS
        self.assertAlmostEqual(decoded[-1] - decoded[0], expected, delta=.5)
        self.assertGreaterEqual(len(decoded), expected * config.VIDEO_RING_FPS - 2)

        # Fotos alrededor de la frase, también antes de ella.
        frames = [f for f in store.event_frames if f.event_id == evidence.event_id]
        self.assertEqual([f.offset_seconds for f in frames], list(config.EVENT_FRAME_OFFSETS_SECONDS))
        self.assertTrue(all(f.image_path for f in frames))
        self.assertTrue(all((config.BASE_DIR / f.image_path).exists() for f in frames))
        # La misma frase no se vuelve a analizar: se sigue después de la ventana completa.
        self.assertGreaterEqual(following, self.WINDOW_START * RATE + int(config.AUDIO_WINDOW_SECONDS * RATE))
        self.assertIn('conservado', session.results[0]['outcome'])

    def test_another_live_camera_records_when_the_microphone_camera_does_not(self):
        now = time.monotonic()
        fill_ring(live_2, config.SECOND_CAMERA_ID, now)  # sólo transmite la webcam USB
        self.shout()
        evidence = store.evidence[0]
        self.assertEqual(evidence.camera_id, config.DEFAULT_CAMERA_ID)  # el micrófono
        self.assertEqual(evidence.video_status, 'ATTACHED')
        self.assertEqual(evidence.video_camera_id, config.SECOND_CAMERA_ID)  # la imagen

    def test_every_live_camera_keeps_its_angle_of_the_same_moment(self):
        now = time.monotonic()
        fill_ring(live_1, config.DEFAULT_CAMERA_ID, now)
        fill_ring(live_2, config.SECOND_CAMERA_ID, now)
        self.shout()
        evidence = store.evidence[0]
        self.assertEqual(evidence.video_camera_id, config.DEFAULT_CAMERA_ID)
        self.assertEqual([v['camera_id'] for v in evidence.extra_videos], [config.SECOND_CAMERA_ID])
        extra = evidence.extra_videos[0]
        self.assertTrue(verify_video_integrity(evidence, extra['file'], extra['integrity_hash']))

    def test_a_live_slot_bound_to_a_network_camera_keeps_its_video(self):
        # En /live se puede asignar a la cámara del equipo cualquier cámara de la red. Aunque en
        # la red figure como simulada, lo que transmite es real y su video debe conservarse.
        network = next(c.id for c in store.cameras if c.stream_source == 'simulated')
        fill_ring(live_1, network, time.monotonic())
        self.shout()
        evidence = store.evidence[0]
        self.assertEqual(evidence.video_status, 'ATTACHED')
        self.assertEqual(evidence.video_camera_id, network)
        frames = [f for f in store.event_frames if f.event_id == evidence.event_id]
        self.assertTrue(frames and all(f.image_path for f in frames))

    def test_each_listening_session_has_its_own_stop_signal(self):
        # Pausar y reanudar mientras la primera transcripción sigue en curso (la primera vez se
        # descarga el modelo de voz): el análisis anterior no debe revivir junto al nuevo.
        from types import SimpleNamespace
        stream = SimpleNamespace(start=lambda: None, stop=lambda: None, close=lambda: None)
        session = MonitoringSession(camera_id=config.DEFAULT_CAMERA_ID, actor='Operador01')
        with patch('sounddevice.InputStream', return_value=stream), patch('services.voice_service.warm_up'):
            session.start()
            first = session._stop
            session.stop()
            session.start()
            try:
                self.assertIsNot(session._stop, first)
                self.assertTrue(first.is_set())
                self.assertFalse(session._stop.is_set())
            finally:
                session.stop()

    def test_a_late_analysis_keeps_its_event_but_not_the_new_session_audio(self):
        import threading
        session = MonitoringSession(camera_id=config.DEFAULT_CAMERA_ID, actor='Operador01')
        previous = threading.Event()
        previous.set()  # la sesión de ese análisis ya terminó; la escucha actual es otra
        session.status = 'ESCUCHANDO'
        session.ring.write(tone(self.RECORDED))
        segments = [{'text': 'por favor déjame, necesito ayuda', 'start': 1.0, 'end': 3.0}]
        with patch('services.monitoring_service.transcribe_window',
                   return_value=(segments[0]['text'], {'segments': segments})):
            session._analyze(self.WINDOW_START * RATE, (self.WINDOW_START + 6) * RATE, -1.0, previous)
        self.assertEqual(store.evidence, self.snapshot[3])  # sin clip con audio de otra sesión
        self.assertTrue(any(v.text_original == segments[0]['text'] for v in store.voice_events))  # el evento sí
        session._loop(previous)
        self.assertEqual(session.status, 'ESCUCHANDO')  # el rezagado no apaga la escucha actual

    def test_without_any_live_camera_the_video_is_declared_pending(self):
        self.shout()
        evidence = store.evidence[0]
        self.assertEqual(evidence.video_status, 'PENDING_INTEGRATION')
        self.assertIsNone(evidence.video_file)
        self.assertTrue(verify_integrity(evidence))  # el audio sí quedó protegido
        frames = [f for f in store.event_frames if f.event_id == evidence.event_id]
        self.assertTrue(frames and all(f.processing_status == 'PENDIENTE_INTEGRACION' for f in frames))

    def test_the_trigger_is_the_phrase_not_the_edge_of_the_window(self):
        offset = MonitoringSession.trigger_offset
        self.assertEqual(offset({'segments': [{'text': 'hola, qué tal', 'start': .2},
                                              {'text': '¡ayuda, suéltame!', 'start': 3.1}]}), 3.1)
        # Si ninguna frase aislada suena a auxilio (lo decidió el contexto), la primera con voz.
        self.assertEqual(offset({'segments': [{'text': 'oye', 'start': 1.4}, {'text': 'ya', 'start': 2}]}), 1.4)
        self.assertEqual(offset({}), 0.0)

    def test_an_early_phrase_still_gets_its_seconds_before(self):
        """Aunque la frase esté al inicio de la ventana, el clip conserva los 5 s previos."""
        now = time.monotonic()
        fill_ring(live_1, config.DEFAULT_CAMERA_ID, now)
        self.shout(phrase_start=.3)
        evidence = store.evidence[0]
        self.assertAlmostEqual(evidence.audio_duration,
                               config.EVIDENCE_PRE_SECONDS + config.EVIDENCE_POST_SECONDS, delta=.2)
        self.assertEqual(evidence.video_status, 'ATTACHED')


if __name__ == '__main__':
    unittest.main()
