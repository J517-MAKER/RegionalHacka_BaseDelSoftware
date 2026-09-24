"""Flujo integrado: cámaras activas, evento, perfil de búsqueda y candidatos priorizados.

Estas pruebas vigilan sobre todo lo que el sistema NO debe hacer: afirmar identidades,
descartar detecciones por ser anteriores a la ficha, penalizar lo que no pudo compararse
o permitir que una sola persona valide su propia escalación.
"""
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import numpy as np

import config
from models.candidate_match import CANDIDATE_STATES, MatchSignal
from services import store
from services.camera_monitor_service import VideoRing, monitor
from services.event_frames_service import store_event_frames
from services.search_matching_service import (create_search_profile, get_candidates, last_locations,
                                              operator_review, parse_datetime, relevance, run_search,
                                              supervisor_review, tracking_timeline)

CASE = 'BUS-2026-0184'


class CameraMonitoringTest(unittest.TestCase):
    def test_cameras_are_active_without_anyone_starting_them(self):
        """Una cámara conectada emite por sí misma; nadie la 'inicia' desde la interfaz."""
        active = monitor.active_cameras()
        self.assertTrue(active)
        self.assertTrue(all(c.stream_status == 'CAMERA_STREAM_ACTIVE' for c in active))
        # Las desconectadas quedan fuera sin que nadie las apague a mano.
        offline = [c for c in store.cameras if c.status == 'Desconectada']
        self.assertTrue(offline)
        self.assertNotIn(offline[0].id, [c.id for c in active])

    def test_the_rest_of_the_system_does_not_know_the_source_kind(self):
        described = monitor.describe(config.DEFAULT_CAMERA_ID)
        self.assertEqual(described['kind'], 'webcam')
        self.assertEqual(monitor.describe('CAM-001')['kind'], 'simulated')
        self.assertIn('active', described)  # misma forma para cualquier fuente

    def test_video_ring_forgets_what_no_event_claimed(self):
        ring = VideoRing(seconds=.4, fps=20)
        for index in range(5):
            ring.write(f'frame-{index}'.encode())  # el anillo guarda cuadros ya comprimidos
        self.assertTrue(ring.frames)
        time.sleep(.5)
        ring.write(b'frame-nuevo')
        kept = [f[2] for f in ring.frames]
        self.assertEqual(kept, [b'frame-nuevo'])  # lo anterior se sobrescribió

    def test_the_equipment_camera_joins_the_monitoring_by_itself(self):
        """Nadie pulsa un botón para que la cámara del equipo exista."""
        import os
        from services.camera_monitor_service import autostart_enabled
        self.assertTrue(config.CAMERA_AUTOSTART)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('PYTEST_CURRENT_TEST', None)
            self.assertTrue(autostart_enabled())
        # Dentro del arnés de pruebas se desactiva: el dispositivo es de uso exclusivo y
        # abrirlo pelearía con las sesiones que las propias pruebas arrancan.
        with patch.dict(os.environ, {'PYTEST_CURRENT_TEST': 'unittest'}):
            self.assertFalse(autostart_enabled())
        self.assertIn('ensure_live_stream', dir(monitor))

    def test_a_deliberate_pause_is_respected(self):
        """Una pausa humana no la revierte el monitoreo por su cuenta."""
        previous = monitor.paused_by
        self.addCleanup(lambda: setattr(monitor, 'paused_by', previous))
        monitor.paused_by = 'Operador01'
        self.assertFalse(monitor.ensure_live_stream())
        state = monitor.stream_state()
        self.assertEqual(state['state'], 'PAUSADA')
        self.assertFalse(state['automatic'])

    def test_camera_topology_is_explicit(self):
        camera = next(c for c in store.cameras if c.id == 'CAM-007')
        self.assertTrue(camera.nearby_camera_ids)
        self.assertNotIn(camera.id, camera.nearby_camera_ids)


class EventFrameTest(unittest.TestCase):
    def setUp(self):
        self.frames = store.event_frames[:]
        self.logs = store.logs[:]
        self.addCleanup(lambda: (store.event_frames.__setitem__(slice(None), self.frames),
                                 store.logs.__setitem__(slice(None), self.logs)))

    def test_several_frames_are_requested_around_the_event(self):
        """Un solo fotograma puede salir borroso o de perfil: se piden varios."""
        captures = [{'offset': offset, 'frame': None, 'timestamp': datetime.now(),
                     'reason': 'Fuente simulada.'} for offset in config.EVENT_FRAME_OFFSETS_SECONDS]
        frames = store_event_frames('EVENT-TEST-0001', 'CAM-001', captures)
        self.assertEqual(len(frames), len(config.EVENT_FRAME_OFFSETS_SECONDS))
        self.assertEqual([f.offset_seconds for f in frames], list(config.EVENT_FRAME_OFFSETS_SECONDS))

    def test_a_missing_source_is_declared_not_faked(self):
        captures = [{'offset': 0, 'frame': None, 'timestamp': datetime.now(), 'reason': 'Fuente simulada.'}]
        frame = store_event_frames('EVENT-TEST-0002', 'CAM-001', captures)[0]
        self.assertEqual(frame.processing_status, 'PENDIENTE_INTEGRACION')
        self.assertFalse(frame.image_path)  # no se inventa una imagen
        self.assertFalse(frame.face_detected)
        self.assertTrue(any('PENDIENTE_INTEGRACION' in (log.result or '') for log in store.logs))


class EventClipTest(unittest.TestCase):
    """El fragmento tiene que poder verse: una evidencia ilegible no verifica nada."""

    def test_the_clip_is_written_in_a_codec_browsers_can_play(self):
        import av
        from services.camera_monitor_service import VideoRing
        from services.event_frames_service import write_event_clip
        now = time.monotonic()
        window = [(now + i * .2, datetime.now() + timedelta(seconds=i * .2),
                   VideoRing.encode(np.full((240, 320, 3), 20 + i * 4, dtype='uint8')))
                  for i in range(25)]
        path = config.EVIDENCE_VIDEO_DIR / 'EVENT-CODEC-UNITTEST.mp4'
        path.unlink(missing_ok=True)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        write_event_clip('EVENT-CODEC-UNITTEST', 'CAM-008', window)
        self.assertTrue(path.exists())
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            # mp4v produce un archivo válido que ningún navegador decodifica.
            self.assertEqual(stream.codec_context.name, 'h264')
            self.assertEqual(stream.codec_context.pix_fmt, 'yuv420p')
            self.assertEqual(sum(1 for _ in container.decode(video=0)), len(window))

    def test_without_images_there_is_no_empty_clip(self):
        from services.event_frames_service import write_event_clip
        self.assertIsNone(write_event_clip('EVENT-SIN-VIDEO', 'CAM-001', []))


class SearchProfileTest(unittest.TestCase):
    def setUp(self):
        self.profiles = store.search_profiles[:]
        self.logs = store.logs[:]
        self.addCleanup(lambda: (store.search_profiles.__setitem__(slice(None), self.profiles),
                                 store.logs.__setitem__(slice(None), self.logs)))

    def test_profile_keeps_what_the_poster_says_and_nothing_more(self):
        profile = create_search_profile(CASE, actor='Operador01')
        case = next(c for c in store.cases if c.id == CASE)
        self.assertEqual(profile.case_id, CASE)
        self.assertEqual(profile.last_known_location, case.location)
        self.assertEqual(profile.clothing_description, case.person.clothing)
        self.assertFalse(profile.disappearance_time_known)  # la ficha sólo trae la fecha
        self.assertEqual(profile.disclosure_status, 'INTERNAL_ONLY')
        self.assertEqual(profile.search_status, 'SIN_INICIAR')  # importar no es buscar

    def test_unparseable_dates_do_not_invent_a_moment(self):
        self.assertEqual(parse_datetime(''), (None, False))
        self.assertEqual(parse_datetime('sin fecha'), (None, False))
        self.assertEqual(parse_datetime('2026-09-22')[1], False)
        self.assertEqual(parse_datetime('2026-09-22 18:00')[1], True)


class SignalTest(unittest.TestCase):
    def test_unevaluable_signals_do_not_punish_a_candidate(self):
        """No haber podido comparar algo no es evidencia en contra."""
        strong = {'face': MatchSignal('ALTA', '', 1.0)}
        with_unknown = {'face': MatchSignal('ALTA', '', 1.0),
                        'appearance': MatchSignal('NO_EVALUABLE', ''),
                        'route': MatchSignal('NO_EVALUABLE', '')}
        self.assertEqual(relevance(strong), relevance(with_unknown))

    def test_a_distress_event_only_adds_context(self):
        signals = {'face': MatchSignal('MEDIA', '', .6)}
        self.assertGreater(relevance(signals, linked_event=True), relevance(signals))
        # El aporte es pequeño: el evento es contexto, no una afirmación sobre la persona.
        self.assertLess(relevance(signals, linked_event=True) - relevance(signals), .1)
        # Y nunca empuja la prioridad por encima del máximo.
        saturated = {'face': MatchSignal('ALTA', '', 1.0)}
        self.assertEqual(relevance(saturated, linked_event=True), 1.0)

    def test_there_is_no_automatic_identification_state(self):
        self.assertNotIn('PERSON_IDENTIFIED_AUTOMATICALLY', CANDIDATE_STATES)
        self.assertIn('PENDING_HUMAN_REVIEW', CANDIDATE_STATES)


class SearchRunTest(unittest.TestCase):
    def setUp(self):
        self.saved = {name: getattr(store, name)[:] for name in
                      ('search_profiles', 'candidate_matches', 'logs', 'detections')}
        self.addCleanup(lambda: [getattr(store, name).__setitem__(slice(None), value)
                                 for name, value in self.saved.items()])
        patcher = patch('services.search_matching_service.require', return_value='Operador01')
        patcher.start()
        self.addCleanup(patcher.stop)
        create_search_profile(CASE, actor='Operador01')

    def test_a_poster_registered_today_still_reaches_older_detections(self):
        """La ficha se registra después; las detecciones anteriores siguen siendo comparables."""
        candidates = run_search(CASE)
        self.assertTrue(candidates)
        self.assertTrue(all(c.case_id == CASE for c in candidates))
        self.assertTrue(all(c.status == 'PENDING_HUMAN_REVIEW' for c in candidates))

    def test_detections_before_the_disappearance_are_flagged_not_discarded(self):
        case = next(c for c in store.cases if c.id == CASE)
        moment, _ = parse_datetime(case.missing_date)
        early = (moment - timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
        store.detections.insert(0, store.detections[0].__class__(
            'DET-EARLY', CASE, 'CAM-003', early, 88))
        candidates = run_search(CASE)
        flagged = [c for c in candidates if c.temporal_window == 'FUERA_DEL_RANGO_PRIORITARIO']
        self.assertTrue(flagged)  # se conserva para reconstruir la trayectoria previa

    def test_signals_stay_separate_and_no_identity_probability_is_produced(self):
        candidate = run_search(CASE)[0]
        self.assertEqual(set(candidate.signals), {'face', 'temporal', 'geographic', 'appearance', 'route'})
        # La apariencia no se inventa mientras el módulo de Re-ID no exista.
        self.assertEqual(candidate.signal('appearance').level, 'NO_EVALUABLE')
        self.assertLessEqual(candidate.relevance_score, 1.0)
        self.assertNotIn('identificad', candidate.outcome.lower())

    def test_human_review_is_the_only_way_forward(self):
        candidate = run_search(CASE)[0]
        with patch('services.search_matching_service.require', return_value='Supervisor01'):
            # Un supervisor no puede resolver lo que ningún operador le envió.
            with self.assertRaises(ValueError):
                supervisor_review(candidate.candidate_match_id, True)
        with patch('services.search_matching_service.require', return_value='Operador01'):
            operator_review(candidate.candidate_match_id, True)
        self.assertEqual(candidate.status, 'OPERATOR_ACCEPTED_FOR_REVIEW')
        self.assertEqual(candidate.disclosure_status, 'INTERNAL_ONLY')
        with patch('services.search_matching_service.require', return_value='Supervisor01'):
            supervisor_review(candidate.candidate_match_id, True)
        self.assertEqual(candidate.status, 'SUPERVISOR_VALIDATED')
        self.assertEqual(candidate.disclosure_status, 'VALIDATED_FOR_INVESTIGATION')
        self.assertTrue(any('Identidad no confirmada' in log.description for log in store.logs))

    def test_a_reviewed_candidate_is_not_reviewed_twice(self):
        candidate = run_search(CASE)[0]
        with patch('services.search_matching_service.require', return_value='Operador01'):
            operator_review(candidate.candidate_match_id, False)
            with self.assertRaises(ValueError):
                operator_review(candidate.candidate_match_id, True)

    def test_last_validated_and_last_possible_never_mix(self):
        candidates = run_search(CASE)
        with patch('services.search_matching_service.require', return_value='Operador01'):
            operator_review(candidates[0].candidate_match_id, True)
        with patch('services.search_matching_service.require', return_value='Supervisor01'):
            supervisor_review(candidates[0].candidate_match_id, True)
        last = last_locations(CASE)
        self.assertIsNotNone(last['validated'])
        self.assertEqual(last['validated'].status, 'SUPERVISOR_VALIDATED')
        if last['possible']:
            self.assertNotEqual(last['possible'].candidate_match_id, last['validated'].candidate_match_id)

    def test_timeline_only_contains_observed_points(self):
        run_search(CASE)
        timeline = tracking_timeline(CASE)
        self.assertEqual(timeline, sorted(timeline, key=lambda c: c.timestamp))
        self.assertTrue(all(c.camera_id for c in timeline))  # cada punto es una cámara real


class ReIdentificationTest(unittest.TestCase):
    def test_appearance_module_declares_itself_pending_instead_of_guessing(self):
        from services import person_reid_service
        self.assertFalse(person_reid_service.available())
        self.assertIsNone(person_reid_service.appearance_embedding('cualquiera.jpg'))
        comparison = person_reid_service.compare('a', 'b')
        self.assertEqual(comparison['level'], 'NO_EVALUABLE')
        self.assertIsNone(comparison['score'])


if __name__ == '__main__':
    unittest.main()
