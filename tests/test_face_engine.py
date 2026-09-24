"""Facial module: InsightFace embeddings, similarity levels and comparison with cases."""
import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

import config
from services import face_engine, facial_service, store
from services.alert_import_service import compare_with_face_database
from services.cases_service import create_case, photo_data_url

MODEL_READY = face_engine.installed() and face_engine.model_downloaded()


def png_bytes(image):
    import cv2
    return cv2.imencode('.png', image)[1].tobytes()


def unit(*values):
    vector = np.zeros(512, dtype=np.float32)
    vector[:len(values)] = values
    return vector / np.linalg.norm(vector)


def fake_face(x1, y1, x2, y2, score, embedding=True):
    vector = unit(1, 2, 3) if embedding else None
    return SimpleNamespace(bbox=np.array([x1, y1, x2, y2], dtype=np.float32), det_score=np.float32(score),
                           embedding=vector, normed_embedding=vector, age=30)


class FaceEngineUnitTest(unittest.TestCase):
    """No model needed: InsightFace is replaced by a fake detector."""

    def test_similarity_is_cosine_and_scale_free(self):
        a, b = unit(1, 0), unit(0, 1)
        self.assertAlmostEqual(face_engine.similarity(a, a * 7), 1.0, places=5)
        self.assertAlmostEqual(face_engine.similarity(a, b), 0.0, places=5)
        self.assertEqual(face_engine.similarity(np.zeros(512), a), 0.0)

    def test_levels_follow_the_configured_thresholds(self):
        self.assertEqual(face_engine.level_of(config.FACE_LEVEL_HIGH), 'ALTA')
        self.assertEqual(face_engine.level_of(config.FACE_LEVEL_MEDIUM), 'MEDIA')
        self.assertEqual(face_engine.level_of(config.FACE_MATCH_THRESHOLD), 'BAJA')
        self.assertIsNone(face_engine.level_of(config.FACE_MATCH_THRESHOLD - .01))

    def test_reads_arrays_bytes_data_urls_and_paths(self):
        image = np.full((40, 30, 3), 128, dtype=np.uint8)
        content = png_bytes(image)
        self.assertIs(face_engine.read_image(image), image)
        self.assertEqual(face_engine.read_image(content).shape, (40, 30, 3))
        data_url = 'data:image/png;base64,' + base64.b64encode(content).decode()
        self.assertEqual(face_engine.read_image(data_url).shape, (40, 30, 3))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'foto con acentos ñ.png'
            path.write_bytes(content)
            self.assertEqual(face_engine.read_image(path).shape, (40, 30, 3))
        # Demo portraits are vector illustrations: there is no face to analyse.
        self.assertIsNone(face_engine.read_image('/assets/demo/person-1.svg'))
        self.assertIsNone(face_engine.read_image('data:image/png;base64,'))
        self.assertIsNone(face_engine.read_image('no-existe.png'))

    def test_faces_are_sorted_by_prominence_and_need_an_embedding(self):
        detector = SimpleNamespace(get=lambda image: [fake_face(0, 0, 10, 10, .9), fake_face(0, 0, 50, 50, .8),
                                                      fake_face(0, 0, 90, 90, .9, embedding=False)])
        with patch.object(face_engine, 'load', return_value=detector):
            faces = face_engine.analyze(np.zeros((100, 100, 3), dtype=np.uint8))
        self.assertEqual([face.bbox for face in faces], [(0, 0, 50, 50), (0, 0, 10, 10)])
        self.assertEqual(faces[0].embedding.shape, (512,))
        self.assertEqual(faces[0].age, 30)

    def test_unreadable_images_never_load_the_model(self):
        with patch.object(face_engine, 'load', side_effect=AssertionError('no debe cargarse')):
            self.assertIsNone(face_engine.best_face('/assets/demo/person-2.svg'))

    def test_missing_model_without_download_is_a_clear_error(self):
        with patch.object(face_engine, '_app', None), patch.object(face_engine, 'installed', return_value=True), \
                patch.object(face_engine, 'model_downloaded', return_value=False), \
                patch('config.FACE_AUTO_DOWNLOAD', False):
            with self.assertRaises(face_engine.FaceEngineUnavailable) as caught:
                face_engine.load()
        self.assertIn('python -m services.face_engine', str(caught.exception))

    def test_live_camera_registers_a_reference_and_quits(self):
        import cv2
        face = face_engine.FaceResult(bbox=(10, 10, 60, 70), det_score=.9, embedding=unit(1, 0))
        camera = SimpleNamespace(isOpened=lambda: True, release=Mock(),
                                 read=lambda: (True, np.full((120, 160, 3), 120, dtype=np.uint8)))
        keys = iter([ord('r'), ord('q')])
        with patch('cv2.VideoCapture', return_value=camera), patch('cv2.imshow') as shown, \
                patch('cv2.waitKey', side_effect=lambda delay: next(keys)), \
                patch('cv2.getWindowProperty', return_value=1), patch('cv2.destroyAllWindows'), \
                patch('cv2.putText', wraps=cv2.putText) as text, \
                patch.object(face_engine, 'analyze', return_value=[face]):
            self.assertEqual(face_engine.live_camera(), 0)
        labels = [call.args[1] for call in text.call_args_list]
        self.assertIn('Pulsa R para registrar', labels)  # first frame, no reference yet
        self.assertIn('100% ALTA', labels)  # after R the same face is its own reference
        self.assertEqual(shown.call_count, 2)
        camera.release.assert_called_once()

    def test_live_camera_reports_black_frames_and_missing_cameras(self):
        with patch('cv2.putText') as text:
            face_engine.draw_overlay(np.zeros((120, 160, 3), dtype=np.uint8), [], None)
        self.assertIn('Imagen negra: destapa la camara o agrega luz', [call.args[1] for call in text.call_args_list])
        closed = SimpleNamespace(isOpened=lambda: False, release=Mock())
        with patch('cv2.VideoCapture', return_value=closed):
            self.assertEqual(face_engine.live_camera(3), 1)

    def test_comparison_with_cases_ranks_and_counts_only_usable_photos(self):
        faces = {'a.png': SimpleNamespace(embedding=unit(1, 0)), 'b.png': SimpleNamespace(embedding=unit(1, 1)),
                 'c.png': SimpleNamespace(embedding=unit(0, 1))}
        cases = [SimpleNamespace(id=f'BUS-{name}', person=SimpleNamespace(name=name, photos=photos))
                 for name, photos in (('same', ['a.png']), ('near', ['b.png', 'c.png']),
                                      ('other', ['c.png']), ('drawing', ['x.svg']))]
        with patch.object(facial_service, 'reference_face', side_effect=faces.get):
            candidates, compared = facial_service.compare_with_cases(unit(1, 0), cases)
        self.assertEqual(compared, 3)  # the SVG case has no usable face
        self.assertEqual([item['case_id'] for item in candidates], ['BUS-same', 'BUS-near'])
        self.assertEqual((candidates[0]['level'], candidates[0]['percent']), ('ALTA', 100))
        self.assertEqual(candidates[1]['label'], 'coincidencia facial alta')  # cos 45° = 0.71


@unittest.skipUnless(MODEL_READY, 'Modelo facial no descargado: ejecuta python -m services.face_engine')
class FaceEngineModelTest(unittest.TestCase):
    """Real InsightFace inference on the sample photo bundled with the library."""

    @classmethod
    def setUpClass(cls):
        from insightface.data import get_image
        cls.sample = get_image('t1')
        cls.faces = face_engine.analyze(cls.sample)

    def crop(self, face, margin=.6, mirror=False):
        x1, y1, x2, y2 = face.bbox
        dx, dy = int((x2 - x1) * margin), int((y2 - y1) * margin)
        image = self.sample[max(0, y1 - dy):y2 + dy, max(0, x1 - dx):x2 + dx]
        return png_bytes(np.ascontiguousarray(image[:, ::-1]) if mirror else image)

    def test_detects_every_face_with_a_normalised_embedding(self):
        self.assertGreaterEqual(len(self.faces), 5)
        for face in self.faces:
            self.assertEqual(face.embedding.shape, (512,))
            self.assertAlmostEqual(float(np.linalg.norm(face.embedding)), 1.0, places=3)
            self.assertGreaterEqual(face.det_score, config.FACE_MIN_DET_SCORE)

    def test_same_person_matches_and_different_people_do_not(self):
        passed, detail = face_engine.self_check()
        self.assertTrue(passed, detail)

    def test_poster_photo_is_compared_with_the_registered_cases(self):
        """A case registered with one photo is found from another photo of the same person."""
        snapshot = (store.cases[:], store.logs[:])
        self.addCleanup(lambda: (store.cases.__setitem__(slice(None), snapshot[0]),
                                 store.logs.__setitem__(slice(None), snapshot[1])))
        first, second = self.faces[0], self.faces[1]
        with patch('services.cases_service.require', return_value='Operador01'):
            case = create_case({'name': 'Persona de prueba',
                                'photos': [photo_data_url(self.crop(first), 'image/png')]})
        with tempfile.TemporaryDirectory() as folder:
            same, other = Path(folder) / 'misma.png', Path(folder) / 'otra.png'
            same.write_bytes(self.crop(first, margin=.9, mirror=True))
            other.write_bytes(self.crop(second))
            found = compare_with_face_database(same)
            missed = compare_with_face_database(other)
        self.assertEqual(found['status'], 'COINCIDENCIAS_FACIALES')
        self.assertFalse(found['mock'])
        self.assertEqual((found['candidates'][0]['case_id'], found['candidates'][0]['level']), (case.id, 'ALTA'))
        self.assertNotIn(case.id, [item['case_id'] for item in missed['candidates']])


if __name__ == '__main__':
    unittest.main()
