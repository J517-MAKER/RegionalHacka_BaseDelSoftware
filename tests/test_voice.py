import unittest
from unittest.mock import patch
from types import SimpleNamespace
from unittest.mock import Mock
from services import store
from services.voice_service import classify_intent, normalize, process_text, MicrophoneCapture, VoiceError, transcribe_audio
from services.alerts_service import start_alert_tracking


class VoiceTest(unittest.TestCase):
    def setUp(self):
        patcher = patch('config.AI_CONTEXT_ENABLED', False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_normalization(self):
        self.assertEqual(normalize(' ¡AYUDA,  me están siguiendo! '), 'ayuda me estan siguiendo')

    def test_distress(self):
        phrases = {
            'ayuda': 'AUXILIO_GENERAL', 'auxilio': 'AUXILIO_GENERAL', 'ayúdame por favor': 'AUXILIO_GENERAL',
            'ayuda me están siguiendo': 'POSIBLE_SEGUIMIENTO',
            'creo que alguien me viene siguiendo': 'POSIBLE_SEGUIMIENTO',
            'ayuda alguien me está siguiendo': 'POSIBLE_SEGUIMIENTO',
            'no me sigas': 'POSIBLE_SEGUIMIENTO', 'me vienen siguiendo': 'POSIBLE_SEGUIMIENTO',
            'por favor déjame': 'POSIBLE_AGRESION', 'suéltame': 'POSIBLE_AGRESION',
            'aléjate de mí': 'POSIBLE_AGRESION', 'alguien que llame a la policía': 'SOLICITUD_AUTORIDAD',
        }
        for text, subtype in phrases.items():
            with self.subTest(text=text):
                result = classify_intent(text)
                self.assertEqual(result['intencion'], 'SOLICITUD_AUXILIO')
                self.assertEqual(result['subtipo'], subtype)

    def test_commands(self):
        commands = [('iniciar búsqueda del folio 527', 'INICIAR_BUSQUEDA', '527'),
                    ('detener búsqueda del folio 184', 'DETENER_BUSQUEDA', '184'),
                    ('mostrar última detección del folio 184', 'MOSTRAR_ULTIMA_DETECCION', '184'),
                    ('mostrar coincidencias del folio 184', 'MOSTRAR_COINCIDENCIAS', '184'),
                    ('mostrar cámaras cercanas', 'MOSTRAR_CAMARAS_CERCANAS', None),
                    ('continuar seguimiento del folio 184', 'INICIAR_SEGUIMIENTO', '184'),
                    ('detener seguimiento del folio 184', 'DETENER_SEGUIMIENTO', '184'),
                    ('marcar coincidencia como incorrecta', 'DESCARTAR_COINCIDENCIA', None)]
        for text, action, folio in commands:
            with self.subTest(text=text):
                result = classify_intent(text)
                self.assertEqual(result['intencion'], 'COMANDO_AUTORIDAD')
                self.assertEqual(result['accion'], action)
                self.assertEqual(result['parametros'].get('folio'), folio)

    def test_no_match(self):
        for text in ['buenos días', 'mañana tengo clases temprano', 'ayudante', 'iniciar búsqueda', 'detener seguimiento del folio abc']:
            self.assertEqual(classify_intent(text)['intencion'], 'SIN_COINCIDENCIA')

    def test_event_alert_and_tracking_pipeline(self):
        events, alerts, logs = store.voice_events[:], store.alerts[:], store.logs[:]
        try:
            with patch('services.voice_service.require', return_value='Operador01'), patch('services.alerts_service.require', return_value='Operador01'):
                for source in ['MICROPHONE', 'DEMO_TEXT']:
                    event = process_text('¡Ayuda, me están siguiendo!', source=source)
                    self.assertEqual(event.text_original, '¡Ayuda, me están siguiendo!')
                    self.assertEqual(event.location, 'Pasillo B')
                    self.assertIsNone(event.confidence)
                    alert = store.alerts[0]
                    self.assertEqual(alert.voice_event_id, event.id)
                    self.assertEqual(event.status, 'PENDIENTE_REVISION')
                    self.assertTrue(start_alert_tracking(alert.id)['mock'])
                    self.assertFalse(alert.tracking_started)
                count = len(store.alerts)
                self.assertEqual(process_text('mañana tengo clases temprano').intent, 'SIN_COINCIDENCIA')
                self.assertEqual(len(store.alerts), count)
                with self.assertRaises(ValueError):
                    process_text('  ')
        finally:
            store.voice_events[:], store.alerts[:], store.logs[:] = events, alerts, logs

    def test_empty_capture_and_exclusive_lock(self):
        with self.assertRaisesRegex(VoiceError, 'demasiado corto'):
            MicrophoneCapture().stop()
        capture = MicrophoneCapture()
        capture._device_lock.acquire()
        try:
            with self.assertRaisesRegex(VoiceError, 'ocupado'):
                capture.start()
        finally:
            capture._device_lock.release()

    def test_transcription_errors_and_metadata(self):
        model = Mock()
        model.transcribe.return_value = (iter([SimpleNamespace(text=' auxilio ', avg_logprob=-.3, no_speech_prob=.02)]), SimpleNamespace(language='es'))
        with patch('services.voice_service._model', model):
            text, metadata = transcribe_audio([])
            self.assertEqual(text, 'auxilio')
            self.assertEqual(metadata['segments'][0]['avg_logprob'], -.3)
            model.transcribe.return_value = (iter([]), SimpleNamespace(language='es'))
            with self.assertRaisesRegex(VoiceError, 'No se detectó voz'):
                transcribe_audio([])
            model.transcribe.side_effect = RuntimeError('device error')
            with self.assertRaisesRegex(VoiceError, 'No fue posible transcribir'):
                transcribe_audio([])
        with patch('services.voice_service._model', None), patch('config.VOICE_MODEL', 'invalid'):
            with self.assertRaisesRegex(VoiceError, 'No fue posible cargar'):
                transcribe_audio([])
