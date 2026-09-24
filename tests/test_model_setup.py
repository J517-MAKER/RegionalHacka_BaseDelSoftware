"""Modelos listos sin ejecutar nada: se preparan solos al arrancar y lo dicen en palabras simples.

Nada de esto descarga de verdad: el motor facial y el de voz se simulan.
"""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import config
from services import face_engine, voice_service
from services.live_recognition_service import recognition_text
from services.model_setup import ModelSetup, enabled


def face_state(downloaded=False, load=None):
    """El motor facial instalado, sin el modelo en memoria y, si se pide, sin descargar."""
    return [patch.object(face_engine, 'loaded', return_value=False),
            patch.object(face_engine, 'installed', return_value=True),
            patch.object(face_engine, 'model_downloaded', return_value=downloaded),
            patch.object(face_engine, 'load', side_effect=load)]


class ModelSetupTest(unittest.TestCase):
    def run_with(self, patches, action):
        for item in patches:
            item.start()
        try:
            return action()
        finally:
            for item in reversed(patches):
                item.stop()

    def test_never_runs_under_the_tests(self):
        with patch.dict(os.environ, {'PYTEST_CURRENT_TEST': 'unittest'}):
            self.assertFalse(enabled())
            setup = ModelSetup()
            setup.start()
            self.assertIsNone(setup._thread)

    def test_the_face_model_downloads_by_itself_the_first_time(self):
        setup, seen = ModelSetup(), []
        with patch('config.FACE_AUTO_DOWNLOAD', True):
            done = self.run_with(face_state(load=lambda: seen.append(setup.face)), setup.prepare_face)
        self.assertTrue(done)
        self.assertEqual(seen, ['DESCARGANDO'])  # mientras se baja, así se anuncia
        self.assertEqual((setup.face, setup.face_error), ('LISTO', ''))
        self.assertIsNone(setup.notice())

    def test_without_internet_it_says_so_and_retries_by_itself(self):
        setup = ModelSetup()
        error = face_engine.FaceEngineUnavailable('No se pudo descargar el modelo facial. Revisa la conexión a '
                                                  'internet; NEXO lo vuelve a intentar solo.')
        with patch('config.FACE_AUTO_DOWNLOAD', True):
            done = self.run_with(face_state(load=error), setup.prepare_face)
        self.assertFalse(done)  # False: el ciclo lo reintenta
        self.assertEqual(setup.face, 'ERROR')
        text, detail = setup.notice()
        self.assertIn('SE REINTENTA SOLO', text)
        self.assertIn('conexión', detail)
        self.assertNotIn('python -m', detail)  # a nadie se le pide ejecutar un comando

    def test_a_disabled_download_is_respected(self):
        setup = ModelSetup()
        patches = face_state()
        with patch('config.FACE_AUTO_DOWNLOAD', False):
            done = self.run_with(patches, setup.prepare_face)
        self.assertTrue(done)
        self.assertEqual(setup.face, 'DESACTIVADO')
        self.assertIsNone(setup.notice())  # decisión deliberada: no es un aviso

    def test_the_voice_model_is_prepared_too(self):
        setup = ModelSetup()
        with patch.object(voice_service, 'model_loaded', return_value=False), \
                patch.object(voice_service, 'model_cached', return_value=False), \
                patch.object(voice_service, 'warm_up', return_value=True):
            self.assertTrue(setup.prepare_voice())
        self.assertEqual(setup.voice, 'LISTO')
        with patch.object(voice_service, 'model_loaded', return_value=False), \
                patch.object(voice_service, 'model_cached', return_value=False), \
                patch.object(voice_service, 'warm_up', return_value=False):
            self.assertFalse(setup.prepare_voice())
        self.assertEqual(setup.voice, 'ERROR')
        self.assertIn('se reintenta solo'.upper(), setup.notice()[0])

    def test_the_header_tells_how_much_is_downloaded(self):
        setup = ModelSetup()
        setup.face = 'DESCARGANDO'
        with patch.object(face_engine, 'download_progress', return_value=120.4):
            text, detail = setup.notice()
        self.assertEqual(text, 'DESCARGANDO RECONOCIMIENTO FACIAL · 120 MB')
        self.assertIn('La cámara ya graba', detail)
        setup.face, setup.voice = 'LISTO', 'DESCARGANDO'
        self.assertEqual(setup.notice()[0], 'DESCARGANDO DETECCIÓN POR VOZ')

    def test_download_progress_reads_the_archive_being_written(self):
        with tempfile.TemporaryDirectory() as root, patch('config.FACE_MODEL_ROOT', Path(root)):
            self.assertIsNone(face_engine.download_progress())
            archive = Path(root) / 'models' / f'{config.FACE_MODEL}.zip'
            archive.parent.mkdir()
            archive.write_bytes(b'\0' * 2 * 1_048_576)
            self.assertAlmostEqual(face_engine.download_progress(), 2.0)

    def test_the_live_camera_shows_the_download_instead_of_a_command(self):
        slot = SimpleNamespace(recognition='CARGANDO', recognition_error=None)
        with patch.object(face_engine, 'model_downloaded', return_value=False), \
                patch.object(face_engine, 'download_progress', return_value=87.0):
            text = recognition_text(slot)
        self.assertIn('Descargando el modelo facial por primera vez', text)
        self.assertIn('87 MB', text)
        with patch.object(face_engine, 'model_downloaded', return_value=True):
            self.assertEqual(recognition_text(slot), '● Cargando el modelo facial (la cámara ya graba)')


if __name__ == '__main__':
    unittest.main()
