import json
import unittest
from unittest.mock import patch, Mock
import numpy as np
from models.conversation_context import ConversationContext
from models.acoustic_features import AcousticFeatures
from models.semantic_analysis import SemanticAnalysis
from services.context_analysis_service import analyze_conversation_context, heuristic_analysis, ollama_analysis
from services.audio_analysis_service import analyze_audio, audio_windows
from services.risk_fusion_service import fuse_evidence
from services.voice_service import process_text, analyze_text, prune_voice_history, transcribe_window
from services import store


CASES = [
    (['ayer fuimos por tacos'], 'se me atoró uno y necesité ayuda', {'NORMAL'}, False),
    (['estaba haciendo la tarea'], 'mi compañero me ayudó', {'NORMAL'}, False),
    (['estábamos hablando de seguridad'], 'si alguien grita ayuda probablemente está en peligro', {'NORMAL', 'AMBIGUO'}, False),
    (['qué dejaron de tarea', 'creo que los ejercicios del capítulo tres'], 'oye, me están siguiendo', {'POSIBLE_AUXILIO'}, True),
    (['vamos a la cafetería', 'yo quiero comprar algo'], 'por favor déjame, necesito ayuda', {'POSIBLE_AUXILIO', 'ALTA_PRIORIDAD'}, True),
    (['ayer iba caminando a casa'], 'y un señor me estuvo siguiendo varias calles', {'NORMAL', 'AMBIGUO'}, False),
    ([], 'auxilio', {'AMBIGUO', 'POSIBLE_AUXILIO'}, None),
    ([], 'buenos días, ¿cómo estás?', {'NORMAL'}, False),
    (['conversación ordinaria'], 'no me sigas, ya te dije que me dejes', {'POSIBLE_AUXILIO'}, True),
    (['en la película el personaje gritó'], 'ayuda, auxilio, me están siguiendo', {'NORMAL', 'AMBIGUO'}, False),
]


class ContextTest(unittest.TestCase):
    def setUp(self):
        self.events, self.alerts, self.logs = store.voice_events[:], store.alerts[:], store.logs[:]
        self.patches = [patch('config.AI_CONTEXT_ENABLED', False), patch('services.voice_service.require', return_value='Operador01')]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        store.voice_events[:], store.alerts[:], store.logs[:] = self.events, self.alerts, self.logs

    def test_ten_required_cases_through_alert_pipeline(self):
        for previous, text, expected, alert_expected in CASES:
            with self.subTest(text=text):
                context = ConversationContext()
                for phrase in previous:
                    context.add(phrase)
                count = len(store.alerts)
                event = process_text(text, context=context)
                self.assertIn(event.classification, expected)
                self.assertEqual(event.assessment.semantic_analysis.mode, 'Fallback local')
                if alert_expected is not None:
                    self.assertEqual(len(store.alerts) - count, int(alert_expected))
                if len(store.alerts) > count:
                    self.assertEqual(store.alerts[0].priority, event.priority)
                    self.assertEqual(event.status, 'PENDIENTE_REVISION')

    def test_regression_and_context_override(self):
        for text in ['ayer estaba comiendo tacos, se me atoró uno y necesité ayuda',
                     'ayer necesité ayuda con mi tarea', 'mi mamá me pidió ayuda para mover una mesa']:
            self.assertEqual(heuristic_analysis([], text).classification, 'NORMAL')
        self.assertEqual(heuristic_analysis(['ayer pedí ayuda'], 'pero ahora me están siguiendo').classification, 'POSIBLE_AUXILIO')
        self.assertEqual(heuristic_analysis([], 'suéltame, ayuda').classification, 'ALTA_PRIORIDAD')

    def test_energy_never_decides_alone_and_quiet_help_survives(self):
        high = analyze_audio(np.ones(16000) * .78, [.30, .28, .32, .31])
        self.assertTrue(high.abrupt_change)
        self.assertIsNotNone(high.energy_variation)
        normal = heuristic_analysis([], 'ayer necesité ayuda con mi tarea')
        self.assertFalse(fuse_evidence(normal, high).should_create_alert)
        help_ = heuristic_analysis([], 'por favor ayúdame esa persona me está siguiendo')
        quiet = analyze_audio(np.ones(16000) * .001, [.1, .1])
        self.assertTrue(fuse_evidence(help_, quiet).should_create_alert)
        self.assertEqual(fuse_evidence(help_, high).classification, 'ALTA_PRIORIDAD')
        # «ayuda» a secas es una petición por su lenguaje, no por el volumen: dicha en voz
        # baja también alerta. El audio sólo agrava lo que el lenguaje ya señaló.
        alone = heuristic_analysis([], 'ayuda')
        self.assertTrue(fuse_evidence(alone, quiet).should_create_alert)
        self.assertEqual(fuse_evidence(alone, quiet).classification, 'POSIBLE_AUXILIO')
        self.assertEqual(fuse_evidence(alone, high).classification, 'ALTA_PRIORIDAD')
        # Una frase configurada que no describe una petición sigue pidiendo más contexto.
        from services import store
        previous = list(store.phrases)
        try:
            store.phrases.append('la sombra')
            ambiguous = heuristic_analysis([], 'la sombra')
            self.assertEqual(fuse_evidence(ambiguous, high).classification, 'AMBIGUO')
        finally:
            store.phrases[:] = previous
        self.assertFalse(analyze_audio(None).available)
        self.assertFalse(analyze_audio([float('nan')] * 16000).available)
        self.assertFalse(analyze_audio(np.ones(16000)).abrupt_change)

    def test_context_expiry_bound_and_isolation(self):
        clock = [100.]
        context = ConversationContext(clock=lambda: clock[0])
        context.add('ayer fuimos por tacos')
        self.assertEqual(len(context.recent()), 1)
        self.assertEqual(ConversationContext().recent(), [])
        clock[0] += 21
        self.assertEqual(context.recent(), [])
        for _ in range(30):
            context.add('x' * 5000)
        self.assertEqual(len(context.recent()), 8)
        self.assertEqual(len(context.recent()[0].text), 2000)
        event = process_text('buenos días')
        with patch('services.voice_service.monotonic', return_value=event.expires_at + 1):
            prune_voice_history()
        self.assertNotIn(event, store.voice_events)
        self.assertFalse(any('buenos días' in log.description for log in store.logs))

    def test_windows_and_overlap_deduplication(self):
        windows = list(audio_windows(np.zeros(14 * 16000)))
        self.assertEqual([(a, b) for a, b, _ in windows], [(0, 6), (4, 10), (8, 14)])
        segments = [{'text': 'anterior', 'start': 0, 'end': 1.5}, {'text': 'nuevo', 'start': 2, 'end': 5}]
        with patch('services.voice_service.transcribe_audio', return_value=('anterior nuevo', {'segments': segments})):
            text, _ = transcribe_window([], 4, 6)
        self.assertEqual(text, 'nuevo')

    def test_provider_failures_use_explicit_fallback(self):
        with patch('config.AI_CONTEXT_ENABLED', True), patch.dict('services.context_analysis_service.PROVIDERS', {'broken': Mock(side_effect=TimeoutError)}), patch('config.AI_PROVIDER', 'broken'):
            result = analyze_conversation_context(['ayer fuimos por tacos'], 'necesité ayuda')
            self.assertEqual(result.mode, 'Fallback local')
            self.assertEqual(result.classification, 'NORMAL')
            self.assertIsNotNone(result.fallback_reason)

    def test_real_provider_contract_with_fake_transport(self):
        data = heuristic_analysis([], 'me están siguiendo').model_dump(exclude={'mode', 'fallback_reason'})
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'message': {'content': json.dumps(data)}}).encode()
        with patch('services.context_analysis_service.urlopen', return_value=response) as request:
            result = ollama_analysis(['hola'], 'me están siguiendo')
            self.assertEqual(result.mode, 'IA contextual')
            payload = json.loads(request.call_args.args[0].data)
            self.assertEqual(payload['format']['additionalProperties'], False)
            self.assertFalse(payload['stream'])
            response.read.return_value = b'{"message":{"content":"not json"}}'
            with patch('config.AI_CONTEXT_ENABLED', True):
                self.assertEqual(analyze_conversation_context([], 'hola').mode, 'Fallback local')
            data['request_is_current'] = False
            response.read.return_value = json.dumps({'message': {'content': json.dumps(data)}}).encode()
            with self.assertRaises(ValueError):
                ollama_analysis([], 'hola')

    def test_sequential_audio_context_and_metadata(self):
        context = ConversationContext()
        risk, _ = analyze_text('qué dejaron de tarea', context, np.ones(16000) * .3)
        risk, previous = analyze_text('me están siguiendo', context, np.ones(16000) * .78)
        self.assertEqual(previous, ['qué dejaron de tarea'])
        self.assertTrue(risk.context_break)
        self.assertEqual(risk.classification, 'ALTA_PRIORIDAD')
