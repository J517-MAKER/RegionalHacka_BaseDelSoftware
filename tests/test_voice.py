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

    def test_authority_commands_are_not_handled_here(self):
        """Administrative orders belong to the assistant; /voice only detects distress."""
        for text in ['iniciar búsqueda del folio 527', 'mostrar coincidencias del folio 184',
                     'mostrar cámaras cercanas', 'marcar coincidencia como incorrecta']:
            with self.subTest(text=text):
                self.assertEqual(classify_intent(text)['intencion'], 'SIN_COINCIDENCIA')
        import services.voice_service as voice_service
        self.assertFalse(hasattr(voice_service, 'process_voice_command'))
        self.assertFalse(hasattr(voice_service, 'COMMANDS'))

    def test_a_bare_cry_for_help_is_enough(self):
        """Quien grita pidiendo ayuda rara vez construye una frase completa."""
        from services.voice_service import analyze_text
        for text in ['ayuda', 'auxilio', 'socorro', 'ayúdame']:
            with self.subTest(text=text):
                risk, _ = analyze_text(text)
                self.assertTrue(risk.should_create_alert, f'{text} debería alertar')
        # Los guardas de contexto siguen evitando el falso positivo.
        for text in ['ayúdame con la tarea', 'ayer necesité ayuda', 'no necesito ayuda']:
            with self.subTest(text=text):
                self.assertFalse(analyze_text(text)[0].should_create_alert, f'{text} no debería alertar')

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
                count, logged = len(store.alerts), len(store.logs)
                self.assertEqual(process_text('mañana tengo clases temprano').intent, 'SIN_COINCIDENCIA')
                self.assertEqual(len(store.alerts), count)
                # La conversación ordinaria no deja rastro en la bitácora (con la escucha continua
                # serían cientos de registros por hora).
                self.assertEqual(len(store.logs), logged)
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
