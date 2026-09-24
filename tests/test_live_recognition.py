"""Live recognition: webcam frames -> faces -> people being searched -> detections for review."""
import asyncio
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from nicegui.storage import Storage
from nicegui.testing import user_simulation

import config
from models.evidence_event import EvidenceEvent
from services import face_engine, store
from services.cameras_service import get_camera
from services.live_recognition_service import LiveRecognition, LiveRecognitionError, next_id

MAIN = Path(__file__).resolve().parents[1] / 'main.py'
FAKE_DEVICES = [{'index': 0, 'name': 'Integrated Camera', 'kind': 'laptop'},
                {'index': 1, 'name': 'USB Webcam', 'kind': 'usb'}]


def unit(*values):
    vector = np.zeros(512, dtype=np.float32)
    vector[:len(values)] = values
    return vector / np.linalg.norm(vector)


def face(bbox=(100, 80, 220, 230), score=.9, embedding=None):
    return face_engine.FaceResult(bbox=bbox, det_score=score, embedding=unit(1, 0) if embedding is None else embedding)


def fake_analyze(image):
    """Every raster image has the same face; the demo SVG portraits have none, as in reality."""
    return [] if isinstance(image, str) and image.endswith('.svg') else [face()]


class FakeCamera:
    def __init__(self, working=True):
        self.working, self.released = working, False

    def isOpened(self):
        return self.working

    def read(self):
        time.sleep(.01)
        return (True, np.full((480, 640, 3), 90, dtype=np.uint8)) if self.working else (False, None)

    def release(self):
        self.released = True


def snapshot_store():
    state = (store.cases[:], store.detections[:], store.matches[:], store.logs[:],
             [(camera, camera.status, camera.last_seen) for camera in store.cameras])

    def restore():
        store.cases[:], store.detections[:], store.matches[:], store.logs[:] = state[:4]
        for camera, status, seen in state[4]:
            camera.status, camera.last_seen = status, seen
    return restore


class LiveRecognitionTest(unittest.TestCase):
    def setUp(self):
        self.restore = snapshot_store()
        self.live = LiveRecognition()
        self.case = store.cases[0]  # BUS-2026-0184, en búsqueda
        self.live.gallery = [(self.case, unit(1, 0))]
        self.frame = np.full((480, 640, 3), 90, dtype=np.uint8)

    def tearDown(self):
        self.live.stop()
        self.restore()

    def test_each_face_gets_its_best_case_and_level(self):
        other = SimpleNamespace(id='BUS-X', person=SimpleNamespace(name='Otra persona'))
        self.live.gallery = [(self.case, unit(1, 1)), (other, unit(0, 1)), (self.case, unit(1, 0))]
        found = self.live._identify(face(embedding=unit(1, 0)))
        self.assertEqual((found['case_id'], found['level']), (self.case.id, 'ALTA'))
        self.assertAlmostEqual(found['similarity'], 1.0, places=5)
        unknown = self.live._identify(face(embedding=unit(0, 0, 1)))
        self.assertEqual((unknown['case_id'], unknown['level']), (None, None))
        self.live.gallery = []
        self.assertIsNone(self.live._identify(face())['level'])

    def test_one_detection_per_window_keeping_the_best_capture(self):
        found = self.live._identify(face())
        weaker = dict(found, similarity=.55, level='MEDIA')
        self.live._record(self.frame, weaker)
        self.live._record(self.frame, found)  # same window: same detection, better capture
        self.assertEqual(len(self.live.detections), 1)
        detection = self.live.detections[0]['detection']
        self.assertEqual((detection.case_id, detection.camera_id, detection.similarity, detection.quality),
                         (self.case.id, config.DEFAULT_CAMERA_ID, 100, 'Adecuada'))
        self.assertTrue(detection.capture.startswith('data:image/jpeg;base64,'))
        self.assertIs(store.detections[0], detection)
        self.assertEqual((store.matches[0].detection_id, store.matches[0].status),
                         (detection.id, 'Pendiente de validación'))
        self.assertEqual(get_camera(config.DEFAULT_CAMERA_ID).status, 'Posible coincidencia')
        self.assertTrue(any('Posible coincidencia facial en vivo' in log.description for log in store.logs))
        with patch('config.LIVE_DETECTION_COOLDOWN_SECONDS', 0):
            self.live._record(self.frame, weaker)  # after the window: a new detection
        self.assertEqual(len(self.live.detections), 2)
        self.assertNotEqual(self.live.detections[0]['detection'].id, detection.id)
        self.assertEqual(next_id([SimpleNamespace(id='DET-009'), SimpleNamespace(id='DET-010')], 'DET'), 'DET-011')

    def test_frame_and_portrait_come_from_the_newest_frame(self):
        self.assertIsNone(self.live.frame_jpeg())
        with self.assertRaises(LiveRecognitionError):
            self.live.capture_face_photo()
        self.live._frame = self.frame
        with self.assertRaisesRegex(LiveRecognitionError, 'No hay un rostro'):
            self.live.capture_face_photo()
        self.live.faces = [self.live._identify(face()), self.live._identify(face(embedding=unit(0, 1)))]
        self.assertTrue(self.live.frame_jpeg().startswith(b'\xff\xd8'))
        self.assertTrue(self.live.capture_face_photo().startswith('data:image/jpeg;base64,'))

    def test_session_uses_the_camera_and_releases_it(self):
        camera = FakeCamera()
        with patch.object(face_engine, 'load'), patch('cv2.VideoCapture', return_value=camera), \
                patch.object(face_engine, 'analyze', return_value=[face()]), \
                patch('services.facial_service.search_gallery', return_value=[(self.case, unit(1, 0))]):
            self.live.start('CAM-003', 0, 'Operador01')
            deadline = time.monotonic() + 5
            while not self.live.detections and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertEqual((self.live.running, self.live.status), (True, 'RECONOCIENDO'))
            self.assertIsNotNone(self.live.frame_jpeg())
            self.assertEqual(self.live.gallery_counts(), {self.case.id: 1})
            self.live.stop('Operador01')
        self.assertTrue(camera.released)
        self.assertEqual((self.live.running, self.live.status, self.live.frame_jpeg()), (False, 'DETENIDA', None))
        detection = self.live.detections[0]['detection']
        self.assertEqual((detection.case_id, detection.camera_id), (self.case.id, 'CAM-003'))

    def test_start_explains_camera_and_model_problems(self):
        # Sin modelo facial la cámara NO se queda apagada: transmite y graba su anillo de
        # evidencia, y el motivo por el que no reconoce rostros queda a la vista.
        with patch.object(face_engine, 'load', side_effect=face_engine.FaceEngineUnavailable('Falta el modelo facial.')), \
                patch('cv2.VideoCapture', return_value=FakeCamera()):
            self.live.start('CAM-003', 0, 'Operador01')
            deadline = time.monotonic() + 5
            while (self.live.recognition != 'NO_DISPONIBLE' or not self.live.ring.frames) \
                    and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(self.live.running)
            self.assertEqual(self.live.status, 'EN VIVO')
            self.assertEqual(self.live.recognition, 'NO_DISPONIBLE')
            self.assertIn('Falta el modelo facial', self.live.recognition_error)
            self.assertTrue(self.live.ring.frames)  # la evidencia se sigue grabando
            self.assertEqual(self.live.faces, [])
            self.live.stop('Operador01')
        self.assertEqual(self.live.ring.frames, [])  # nada de lo visto sobrevive a la sesión
        closed = FakeCamera(working=False)
        with patch.object(face_engine, 'load'), patch('cv2.VideoCapture', return_value=closed):
            with self.assertRaisesRegex(LiveRecognitionError, 'No fue posible abrir la cámara'):
                self.live.start()
        self.assertTrue(closed.released)
        self.assertFalse(self.live.running)

    def test_two_simultaneous_starts_open_the_camera_once(self):
        # El monitoreo continuo reintenta y el botón REANUDAR arranca: pueden coincidir.
        opened = []

        def slow_start(camera_id, camera_index, actor):
            opened.append(actor)
            time.sleep(.2)
            self.live.running = True

        with patch.object(self.live, '_start', side_effect=slow_start):
            callers = [threading.Thread(target=self.live.start, kwargs={'actor': actor})
                       for actor in ('Sistema · monitoreo continuo', 'Operador01')]
            for caller in callers:
                caller.start()
            for caller in callers:
                caller.join()
        self.assertEqual(len(opened), 1)
        self.live.running = False

    def test_each_session_has_its_own_stop_signal(self):
        # Un hilo de la sesión anterior que tardó en salir (p. ej. descargando el modelo) no
        # debe revivir cuando la cámara se reanuda.
        with patch.object(face_engine, 'load'), patch.object(face_engine, 'analyze', return_value=[]), \
                patch('cv2.VideoCapture', side_effect=lambda *args: FakeCamera()):
            self.live.start('CAM-003', 0, 'Operador01')
            first = self.live._stop
            self.live.stop('Operador01')
            self.live.start('CAM-003', 0, 'Operador01')
            self.assertIsNot(self.live._stop, first)
            self.assertTrue(first.is_set())
            self.assertFalse(self.live._stop.is_set())
            self.live.stop('Operador01')

    def test_a_damaged_frame_does_not_freeze_the_stream(self):
        class Flaky(FakeCamera):
            reads = 0

            def read(self):
                self.reads += 1
                if self.reads == 3:  # la primera lectura es la de prueba al abrir
                    raise RuntimeError('cuadro dañado')
                return super().read()

        camera = Flaky()
        with patch.object(face_engine, 'load'), patch.object(face_engine, 'analyze', return_value=[]), \
                patch('cv2.VideoCapture', return_value=camera):
            self.live.start('CAM-003', 0, 'Operador01')
            deadline = time.monotonic() + 5
            while camera.reads < 12 and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(self.live.running)
            self.assertIsNotNone(self.live.frame_jpeg())
            self.live.stop('Operador01')
        self.assertGreaterEqual(camera.reads, 12)
        self.assertTrue(camera.released)

    def test_faces_in_view_are_linked_to_a_request_for_help(self):
        self.live.running, self.live.camera_id, self.live._frame = True, 'CAM-008', self.frame
        self.live.faces = [self.live._identify(face())]
        self.assertEqual(self.live.snapshot_faces('CAM-001'), [])  # another camera saw nothing
        evidence = EvidenceEvent('EVENT-TEST', 'CAM-008', 'Pasillo B', store.now(), 'POSIBLE_AUXILIO', 'ALTA')
        LiveRecognition.attach_faces_to_evidence(evidence, self.live.snapshot_faces('CAM-008'))
        self.assertEqual((evidence.face_captures[0]['case_id'], evidence.face_captures[0]['similarity']),
                         (self.case.id, 100))
        from services.voice_integrations import request_person_detection
        with patch('services.live_recognition_service.live', self.live):
            result = request_person_detection('CAM-008', 'ALERT-1')
        self.assertEqual((result['status'], result['mock'], len(result['faces'])), ('VISION_ACTIVE', False, 1))
        self.assertEqual(self.live.current_face('CAM-008')['case_id'], self.case.id)
        self.live.running = False


class SessionDevicesTest(unittest.TestCase):
    """Cambiar de perfil es un relevo: el puesto nuevo no hereda los dispositivos del anterior."""

    def setUp(self):
        from services.camera_monitor_service import monitor
        self.monitor = monitor
        self.role = monitor.role
        self.audio = monitor._audio
        self.logs = store.logs[:]

    def tearDown(self):
        self.monitor.role, self.monitor._audio = self.role, self.audio
        store.logs[:] = self.logs

    def test_administrator_releases_camera_and_continuous_listening(self):
        from services.camera_monitor_service import monitor
        stopped = []
        listening = SimpleNamespace(running=True, stop=lambda: stopped.append('microfono'))
        monitor._audio = listening
        instance = SimpleNamespace(running=True)
        with patch('services.live_recognition_service.LIVE_INSTANCES', [instance]),                 patch('services.live_recognition_service.stop_all',
                      lambda actor=None: stopped.append('camaras')):
            released = monitor.apply_role('Administrador', 'Admin01')
        self.assertEqual(sorted(stopped), ['camaras', 'microfono'])
        self.assertEqual(len(released), 2)
        # Y el monitoreo continuo tampoco vuelve a abrirlos por su cuenta.
        self.assertFalse(monitor.allows('camera'))
        self.assertFalse(monitor.allows('microphone'))
        self.assertFalse(monitor.ensure_live_stream())
        self.assertFalse(monitor.ensure_audio_stream())
        self.assertEqual(store.logs[0].result, 'LIBERADO')

    def test_operator_keeps_its_own_devices(self):
        from services.camera_monitor_service import monitor
        monitor._audio = None
        released = monitor.apply_role('Operador', 'Operador01')
        self.assertEqual(released, [])
        self.assertTrue(monitor.allows('camera') and monitor.allows('microphone'))


class LivePageTest(unittest.IsolatedAsyncioTestCase):
    async def wait_for(self, condition, seconds=6):
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            await asyncio.sleep(.1)
        self.assertTrue(condition())

    async def test_register_a_person_from_the_camera_and_find_them_live(self):
        """The whole flow from the web: start, register from the webcam, live detection, stop."""
        restore = snapshot_store()
        self.addCleanup(restore)
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {'PYTEST_CURRENT_TEST': 'unittest', 'NICEGUI_SCREEN_TEST_PORT': '8081'}), \
                patch.object(Storage, 'path', Path(directory) / 'storage'), \
                patch('config.LIVE_GALLERY_REFRESH_SECONDS', .2), patch.object(face_engine, 'load'), \
                patch('cv2.VideoCapture', return_value=FakeCamera()), \
                patch('services.live_recognition_service.list_video_devices', return_value=FAKE_DEVICES), \
                patch.object(face_engine, 'analyze', side_effect=fake_analyze):
            async with user_simulation(main_file=MAIN) as user:
                from services.live_recognition_service import live
                try:
                    await user.open('/live')
                    await user.should_see(content='Reconocimiento facial en vivo', marker='page-title')
                    user.find(marker='live-start').click()
                    await self.wait_for(lambda: live.running and live.faces)
                    await user.should_see('RECONOCIENDO')

                    user.find(marker='live-register').click()
                    await user.should_see('Nueva búsqueda')
                    user.find('Nombre completo *').type('Persona en vivo QA')
                    user.find('Registrar caso y procesar referencias').click()
                    await self.wait_for(lambda: store.cases[-1].person.name == 'Persona en vivo QA')
                    case = store.cases[-1]
                    self.assertTrue(case.person.photos[0].startswith('data:image/jpeg;base64,'))

                    await self.wait_for(lambda: any(item['detection'].case_id == case.id
                                                    for item in live.detections))
                    await user.should_see(f'Posible coincidencia: {case.id}')

                    # The webcam is also the first camera of the network, live while it runs.
                    await user.open('/cameras')
                    await user.should_see('Pasillo B · cámara del equipo')
                    await user.should_see('● EN VIVO')

                    await user.open('/live')
                    # Pausar es deliberado y se distingue de una cámara que nunca arrancó:
                    # el monitoreo continuo no la reabre por su cuenta.
                    user.find(marker='live-stop').click()
                    await self.wait_for(lambda: not live.running)
                    await user.should_see('PAUSADA')
                    await user.open('/cameras')
                    await user.should_see('Cámara del equipo detenida')
                finally:
                    from services.camera_monitor_service import monitor
                    monitor.paused_by = ''
                    live.stop()


if __name__ == '__main__':
    unittest.main()
