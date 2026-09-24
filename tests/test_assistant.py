"""Administrative voice assistant: interpretation, safe execution, roles and audit."""
import json
import unittest
from unittest.mock import Mock, patch

from models.assistant_command import AssistantCommand
from models.person import Person
from models.search_case import SearchCase
from services import store
from services.admin_voice_assistant_service import execute, handle_command, interpret, ollama_command, rule_command

PHRASES = [
    ('búscame el folio 184', 'OPEN_CASE', {'folio': '184'}),
    ('buscar folio 184', 'OPEN_CASE', {'folio': '184'}),
    ('abre el folio 184', 'OPEN_CASE', {'folio': '184'}),
    ('muéstrame el caso 184', 'OPEN_CASE', {'folio': '184'}),
    ('quiero ver el folio 184', 'OPEN_CASE', {'folio': '184'}),
    ('abre el caso BUS-2026-0184', 'OPEN_CASE', {'folio': '184'}),
    ('oye, búscame por favor el folio 184', 'OPEN_CASE', {'folio': '184'}),
    ('muéstrame la última detección del folio 184', 'SHOW_LAST_DETECTION', {'folio': '184'}),
    ('¿dónde se detectó por última vez el caso 184?', 'SHOW_LAST_DETECTION', {'folio': '184'}),
    ('muéstrame las coincidencias del folio 184', 'SHOW_MATCHES', {'folio': '184'}),
    ('ver coincidencias del caso 184', 'SHOW_MATCHES', {'folio': '184'}),
    ('muéstrame la cámara 8', 'OPEN_CAMERA', {'camera': 'CAM-008'}),
    ('abre CAM-008', 'OPEN_CAMERA', {'camera': 'CAM-008'}),
    ('abre la cámara ocho', 'OPEN_CAMERA', {'camera': 'CAM-008'}),
    ('muéstrame las alertas pendientes', 'SHOW_PENDING_ALERTS', {}),
    ('abre las alertas de hoy', 'SHOW_ALERTS', {}),
    ('busca a María López', 'SEARCH_PERSON', {'person': 'maria lopez'}),
    ('muéstrame el caso de María López', 'SEARCH_PERSON', {'person': 'maria lopez'}),
    ('hola cómo estás', 'UNKNOWN_COMMAND', {}),
    ('pásame aquello de ayer', 'UNKNOWN_COMMAND', {}),
]


def fake_case(case_id, name):
    return SearchCase(case_id, Person(name=name, age='30', sex='No especificado', height='1.70 m',
                                      build='Media', skin='No especificado', hair='Castaño', eyes='Café',
                                      clothing='—', marks='—', description='Prueba'),
                      '2026-09-20', '2026-09-23 08:00', 'Centro', 'Centro', 'Admin01')


class AssistantTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = (store.cases[:], store.logs[:])
        self.patches = [patch('config.AI_CONTEXT_ENABLED', False),
                        patch('services.admin_voice_assistant_service.require', return_value='Admin01')]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        store.cases[:], store.logs[:] = self.snapshot

    def test_natural_language_maps_to_intents(self):
        for text, intent, parameters in PHRASES:
            with self.subTest(text=text):
                command = interpret(text)
                self.assertEqual(command.intent, intent)
                self.assertEqual(command.parameters, parameters)
                self.assertEqual(command.mode, 'Reglas locales')

    def test_open_case_navigates_and_audits(self):
        result = handle_command('búscame el folio 184')
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['route'], '/cases/BUS-2026-0184')
        self.assertIn('BUS-2026-0184', result['message'])
        entry = store.logs[0]
        self.assertEqual((entry.user, entry.kind, entry.result), ('Admin01', 'Comando de voz', 'SUCCESS'))
        self.assertIn('OPEN_CASE', entry.description)
        self.assertIn('búscame el folio 184', entry.description)

    def test_last_detection_matches_and_camera(self):
        last = handle_command('muéstrame la última detección del folio 184')
        self.assertEqual(last['status'], 'SUCCESS')
        self.assertIn('CAM-012', last['detail'])
        self.assertIn('10:25:41', last['detail'])
        self.assertIn('case_id=BUS-2026-0184', last['route'])

        matches = handle_command('muéstrame las coincidencias del folio 184')
        self.assertEqual(matches['route'], '/matches?case_id=BUS-2026-0184')

        camera = handle_command('abre la cámara ocho')
        self.assertEqual(camera['route'], '/cameras?camera_id=CAM-008')
        self.assertEqual(camera['detail'], 'Pasillo B')

    def test_alerts_filter(self):
        self.assertEqual(handle_command('muéstrame las alertas pendientes')['route'],
                         '/alerts?status=PENDIENTE_REVISION')
        self.assertEqual(handle_command('abre las alertas de hoy')['route'], '/alerts')

    def test_unknown_command_executes_nothing(self):
        result = handle_command('hola cómo estás')
        self.assertEqual(result['status'], 'ERROR')
        self.assertIsNone(result['route'])
        self.assertEqual(result['message'], 'No entendí el comando. Intenta decirlo nuevamente.')
        self.assertEqual(store.logs[0].result, 'ERROR')
        self.assertIn('UNKNOWN_COMMAND', store.logs[0].description)

    def test_missing_entities_do_not_guess(self):
        self.assertEqual(execute(AssistantCommand(intent='OPEN_CASE', folio='999'))['status'], 'ERROR')
        self.assertEqual(execute(AssistantCommand(intent='OPEN_CAMERA', camera='CAM-404'))['status'], 'ERROR')
        self.assertEqual(execute(AssistantCommand(intent='SEARCH_PERSON', person='nadie en absoluto'))['status'], 'ERROR')
        with self.assertRaises(ValueError):
            handle_command('   ')

    def test_several_people_require_a_manual_choice(self):
        store.cases.extend([fake_case('BUS-2026-0012', 'Juan Pérez (ficticio)'),
                            fake_case('BUS-2026-0048', 'Juan Rodríguez (ficticio)'),
                            fake_case('BUS-2026-0071', 'Juan Martínez (ficticio)')])
        result = handle_command('búscame a Juan')
        self.assertEqual(result['status'], 'OPTIONS')
        self.assertIsNone(result['route'])
        self.assertEqual(len(result['options']), 3)
        self.assertEqual({o['sublabel'] for o in result['options']},
                         {'BUS-2026-0012', 'BUS-2026-0048', 'BUS-2026-0071'})
        single = handle_command('busca a Juan Rodríguez')
        self.assertEqual(single['route'], '/cases/BUS-2026-0048')

    def test_only_administrators_may_run_commands(self):
        with patch('services.admin_voice_assistant_service.require',
                   side_effect=PermissionError('El rol de esta sesión no permite esta operación.')):
            with self.assertRaises(PermissionError):
                handle_command('búscame el folio 184')
        from services.users_service import PERMISSIONS
        self.assertIn('assistant.use', PERMISSIONS['Administrador'])
        for role in ('Operador', 'Supervisor'):
            self.assertNotIn('assistant.use', PERMISSIONS[role])

    def test_sensitive_intents_are_rejected(self):
        command = AssistantCommand(intent='OPEN_CASE', folio='184')
        for forbidden in ('DELETE_EVIDENCE', 'APPROVE_DELETION', 'DELETE_USER'):
            result = execute(command.model_copy(update={'intent': forbidden}))
            self.assertEqual(result['status'], 'ERROR')
            self.assertIsNone(result['route'])

    def test_provider_contract_and_fallback(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'message': {'content': json.dumps(
            {'intent': 'OPEN_CASE', 'folio': '184', 'person': None, 'camera': None})}}).encode()
        with patch('services.admin_voice_assistant_service.urlopen', return_value=response) as request:
            command = ollama_command('oye, ábreme el expediente ciento ochenta y cuatro')
            self.assertEqual((command.intent, command.folio, command.mode), ('OPEN_CASE', '184', 'IA contextual'))
            payload = json.loads(request.call_args.args[0].data)
            self.assertFalse(payload['stream'])
            self.assertEqual(payload['format']['additionalProperties'], False)
            self.assertNotIn('mode', payload['format']['properties'])
            # An interpretation without its required entity is rejected, not guessed.
            response.read.return_value = json.dumps({'message': {'content': json.dumps(
                {'intent': 'OPEN_CASE', 'folio': None, 'person': None, 'camera': None})}}).encode()
            with self.assertRaises(ValueError):
                ollama_command('abre el caso')
            with patch('config.AI_CONTEXT_ENABLED', True):
                self.assertEqual(interpret('abre el folio 184').mode, 'Reglas locales')


if __name__ == '__main__':
    unittest.main()
