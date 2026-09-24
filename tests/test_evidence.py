"""Audio -> transcription -> context -> classification -> evidence -> review -> deletion."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np

import config
from services import store
from services.audio_buffer import AudioRing
from services.evidence_service import (attach_video_evidence, get_deletion_requests, next_event_id,
                                       request_deletion, resolve_deletion, review_event, verify_integrity,
                                       write_audio)
from services.monitoring_service import MonitoringSession

RATE = config.AUDIO_SAMPLE_RATE


def speech(seconds, amplitude=.2):
    """Deterministic tone; the transcription itself is scripted by the test."""
    t = np.arange(int(seconds * RATE), dtype=np.float32) / RATE
    return (np.sin(2 * np.pi * 180 * t) * amplitude).astype(np.float32)


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = (store.voice_events[:], store.alerts[:], store.logs[:],
                         store.evidence[:], store.deletion_requests[:])
        store.evidence.clear()
        store.deletion_requests.clear()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        audio_dir = Path(self.directory.name) / 'audio'
        self.patches = [patch('config.AI_CONTEXT_ENABLED', False),
                        patch('config.EVIDENCE_AUDIO_DIR', audio_dir),
                        patch('config.EVIDENCE_VIDEO_DIR', Path(self.directory.name) / 'video'),
                        patch('services.evidence_service.require', side_effect=lambda action: self.actor)]
        for item in self.patches:
            item.start()
        self.actor = 'Operador01'
        self.audio_dir = audio_dir

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        (store.voice_events[:], store.alerts[:], store.logs[:],
         store.evidence[:], store.deletion_requests[:]) = self.snapshot

    # ------------------------------------------------------------------ helpers
    def session(self):
        monitor = MonitoringSession(actor='Operador01')
        monitor.started_wall = datetime.now()
        return monitor

    def listen(self, monitor, phrases, amplitude=.2):
        """Feed windows of real samples and scripted transcriptions through the pipeline."""
        window = int(config.AUDIO_WINDOW_SECONDS * RATE)
        results = []
        for phrase in phrases:
            level = amplitude(phrase) if callable(amplitude) else amplitude
            start = monitor.ring.written
            # Window plus post-roll, so the evidence clip is complete without waiting.
            monitor.ring.write(speech(config.AUDIO_WINDOW_SECONDS, level))
            monitor.ring.write(speech(config.EVIDENCE_POST_SECONDS + 1, level))
            with patch('services.monitoring_service.transcribe_window',
                       return_value=(phrase, {'segments': [{'text': phrase, 'start': 0, 'end': 1}]})):
                monitor._analyze(start, start + window, -1.0)
            results.append(monitor.results[0])
        return results

    # ------------------------------------------------------------------ buffer
    def test_ring_keeps_only_the_recent_seconds(self):
        ring = AudioRing(seconds=2)
        ring.write(np.arange(RATE, dtype=np.float32) / RATE)
        ring.write(np.ones(2 * RATE, dtype=np.float32))
        self.assertEqual(ring.oldest(), RATE)
        self.assertEqual(len(ring.read(0, ring.written)), 2 * RATE)
        self.assertTrue(np.allclose(ring.read(ring.written - 10, ring.written), 1))
        self.assertEqual(len(ring.read(ring.written, ring.written + 100)), 0)
        # Lo pedido desde una muestra ya descartada empieza, de verdad, en la más antigua.
        start, samples = ring.read_span(0, RATE + 10)
        self.assertEqual((start, len(samples)), (RATE, 10))

    # ------------------------------------------------------------------ PRUEBA 1
    def test_past_narration_creates_no_evidence(self):
        monitor = self.session()
        result = self.listen(monitor, ['ayer comí tacos y se me atoró uno, ocupé ayuda'])[0]
        self.assertEqual(result['classification'], 'NORMAL')
        self.assertIsNone(result['event_id'])
        self.assertEqual(store.evidence, [])
        self.assertEqual(list(self.audio_dir.glob('*.wav')), [])

    # ------------------------------------------------------------------ PRUEBA 2
    def test_rejection_after_ordinary_conversation(self):
        monitor = self.session()
        results = self.listen(monitor, ['qué dejaron de tarea', 'creo que los ejercicios de la página 40',
                                        'oye, no me sigas'])
        self.assertEqual(results[0]['classification'], 'NORMAL')
        self.assertIn(results[-1]['classification'], ('AMBIGUO', 'POSIBLE_AUXILIO', 'ALTA_PRIORIDAD'))

    # ------------------------------------------------------------------ PRUEBA 3
    def test_current_request_stores_immutable_evidence(self):
        monitor = self.session()
        result = self.listen(monitor, ['vamos a la cafetería', 'por favor déjame, necesito ayuda'])[-1]
        self.assertIn(result['classification'], ('POSIBLE_AUXILIO', 'ALTA_PRIORIDAD'))
        event = store.evidence[0]
        self.assertEqual(result['event_id'], event.event_id)
        path = config.BASE_DIR / event.audio_file
        self.assertTrue(path.exists())
        self.assertEqual(len(event.integrity_hash), 64)
        self.assertTrue(verify_integrity(event))
        # Pre-roll and post-roll are kept around the detected window.
        self.assertGreater(event.audio_duration, config.AUDIO_WINDOW_SECONDS)
        self.assertEqual(event.review_status, 'PENDIENTE_REVISION')
        self.assertIsNone(event.video_file)
        self.assertEqual(event.video_status, 'PENDING_INTEGRATION')
        self.assertTrue(event.transcript_normalized)
        self.assertTrue(event.audio_start_timestamp < event.audio_end_timestamp)
        self.assertTrue(any(a.voice_event_id == event.voice_event_id for a in store.alerts))
        # A tampered file no longer matches the hash recorded at creation.
        path.write_bytes(path.read_bytes() + b'\x00\x00')
        self.assertFalse(verify_integrity(event))

    # ------------------------------------------------------------------ PRUEBA 4
    def test_acoustic_change_raises_priority_but_never_decides_alone(self):
        monitor = self.session()
        loud = self.listen(monitor, ['vamos a la cafetería', 'suéltame, ayuda'],
                           amplitude=lambda phrase: .08 if 'cafetería' in phrase else .6)[-1]
        self.assertEqual(loud['classification'], 'ALTA_PRIORIDAD')
        self.assertEqual(loud['priority'], 'ALTA')
        self.assertTrue(any('acústic' in signal.lower() for signal in loud['signals']))
        quiet = self.session()
        result = self.listen(quiet, ['ayer necesité ayuda con la tarea'], amplitude=.9)[0]
        self.assertEqual(result['classification'], 'NORMAL')
        self.assertIsNone(result['event_id'])

    # ------------------------------------------------------------ PRUEBAS 5 a 8
    def test_review_and_deletion_require_two_people(self):
        monitor = self.session()
        self.listen(monitor, ['vamos a la cafetería', 'por favor déjame, necesito ayuda'])
        event = store.evidence[0]
        path = config.BASE_DIR / event.audio_file

        # PRUEBA 5: a false positive only reclassifies; the audio survives.
        review_event(event.event_id, 'FALSO_POSITIVO', notes='Ensayo de teatro')
        self.assertEqual(event.review_status, 'FALSO_POSITIVO')
        self.assertEqual(event.reviewed_by, 'Operador01')
        self.assertTrue(event.reviewed_at and path.exists())
        self.assertEqual(event.review_notes, 'Ensayo de teatro')

        # PRUEBA 6: the operator may only request a deletion.
        with self.assertRaises(ValueError):
            request_deletion(event.event_id, 'no')
        request = request_deletion(event.event_id, 'Grabación de una práctica escolar')
        self.assertEqual(event.review_status, 'DELETION_REQUESTED')
        self.assertEqual(request.status, 'PENDING')
        self.assertEqual(request.integrity_hash, event.integrity_hash)
        self.assertTrue(path.exists())
        with self.assertRaises(ValueError):
            request_deletion(event.event_id, 'Solicitud duplicada de prueba')
        with self.assertRaises(ValueError):
            review_event(event.event_id, 'CONFIRMADO_PARA_ATENCION')

        # The same person cannot authorise their own request.
        with self.assertRaises(ValueError):
            resolve_deletion(request.request_id, True)

        # PRUEBA 7: a supervisor rejects; the file remains.
        self.actor = 'Supervisor01'
        resolve_deletion(request.request_id, False, 'Debe conservarse para revisión')
        self.assertEqual(event.review_status, 'DELETION_REJECTED')
        self.assertEqual(get_deletion_requests('REJECTED')[0].reviewed_by, 'Supervisor01')
        self.assertTrue(path.exists())

        # PRUEBA 8: a new request is approved; for the prototype nothing is erased.
        self.actor = 'Operador01'
        second = request_deletion(event.event_id, 'Se confirma que fue una práctica escolar')
        self.actor = 'Supervisor01'
        resolve_deletion(second.request_id, True)
        self.assertEqual(event.review_status, 'DELETION_APPROVED')
        self.assertTrue(path.exists())
        self.assertTrue(verify_integrity(event))

        trail = [log.description for log in store.logs]
        for fragment in ['creado automáticamente', 'marcó como falso positivo', 'solicitó eliminación',
                         'rechazó la solicitud', 'aprobó la solicitud']:
            self.assertTrue(any(fragment in entry for entry in trail), fragment)

    # ------------------------------------------------------------------ storage
    def test_identifiers_are_unique_and_files_are_never_overwritten(self):
        first = next_event_id()
        write_audio(first, speech(1))
        self.assertTrue((self.audio_dir / (first + '.wav')).exists())
        with self.assertRaises(ValueError):
            write_audio(first, speech(1))
        self.assertNotEqual(next_event_id(), first)

    def test_video_integration_point(self):
        monitor = self.session()
        self.listen(monitor, ['vamos a la cafetería', 'por favor déjame, necesito ayuda'])
        event = store.evidence[0]
        with self.assertRaises(ValueError):
            attach_video_evidence(event.event_id, 'evidence/video/no-existe.mp4', '', '')
        video = Path(self.directory.name) / 'video' / (event.event_id + '.mp4')
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b'demo')
        attach_video_evidence(event.event_id, video, '2026-09-23 12:34:08', '2026-09-23 12:34:26')
        self.assertEqual(event.video_status, 'ATTACHED')
        self.assertIn(event.event_id, event.video_file)
        self.assertEqual(event.video_start_timestamp, '2026-09-23 12:34:08')


if __name__ == '__main__':
    unittest.main()
