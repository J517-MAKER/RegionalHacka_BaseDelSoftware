"""Base de datos local (SQLite): lo registrado sobrevive a un reinicio, sin Docker.

Simula un reinicio: se guarda, se vuelve a los datos de demostración y se carga. Todo lo que
importa para revisar un caso o una evidencia debe volver igual, con sus tipos y su orden; la
conversación ordinaria nunca se guarda.
"""
import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path

from models.audit_log import AuditLog
from models.candidate_match import CandidateMatch, MatchSignal
from models.detection import Detection
from models.evidence_event import EvidenceEvent
from models.person import Person
from models.search_case import SearchCase
from models.track_sighting import TrackSighting
from models.voice_event import VoiceEvent
from services import store
from services.local_db import LocalDatabase

LISTS = ('cases', 'detections', 'matches', 'evidence', 'alerts', 'voice_events', 'event_frames',
         'person_candidates', 'search_profiles', 'candidate_matches', 'track_sightings', 'deletion_requests',
         'imports', 'users', 'logs')


class LocalDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.saved = {name: getattr(store, name)[:] for name in LISTS}
        # Semillas frescas: otras pruebas dejan en memoria eventos, alertas y cambios de estado.
        from mocks.cases import seed_cases
        from mocks.detections import seed_detections, seed_matches
        from mocks.users import seed_users
        fresh = {'cases': seed_cases(), 'detections': seed_detections(), 'matches': seed_matches(),
                 'users': seed_users()}
        for name in LISTS:
            getattr(store, name)[:] = fresh.get(name, [])
        self.seeds = {name: copy.deepcopy(getattr(store, name)) for name in LISTS}
        self.settings, self.phrases = copy.deepcopy(store.settings), store.phrases[:]
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.restore)
        self.path = Path(self.directory.name) / 'nexo.db'

    def restore(self):
        for name, value in self.saved.items():
            getattr(store, name)[:] = value
        store.settings.clear()
        store.settings.update(self.settings)
        store.phrases[:] = self.phrases

    def restart(self):
        """Lo que haría un reinicio: la memoria vuelve a los datos de demostración."""
        for name in LISTS:
            getattr(store, name)[:] = copy.deepcopy(self.seeds[name])
        store.settings.clear()
        store.settings.update(copy.deepcopy(self.settings))
        store.phrases[:] = self.phrases[:]
        database = LocalDatabase(self.path)
        database.load()
        return database

    def record_everything(self):
        store.cases.append(SearchCase('BUS-2026-0999', Person('Persona de prueba', age='30', clothing='Sudadera roja',
                                                              photos=['data:image/png;base64,AAAA']),
                                      '2026-09-20', '2026-09-21 10:00:00', 'Macroplaza', 'Centro', 'Operador01'))
        store.detections.insert(0, Detection('DET-900', 'BUS-2026-0999', 'CAM-008', '2026-09-24 10:00:00', 71,
                                             embedding=[.1] * 512, estimated_age=29, clothing_color='rojo'))
        evidence = EvidenceEvent('EVENT-20260924-00042', 'CAM-008', 'Pasillo B', '2026-09-24 10:00:05',
                                 'POSIBLE_AUXILIO', 'MEDIA', audio_file='evidence/audio/EVENT-20260924-00042.wav',
                                 trigger_timestamp='2026-09-24 10:00:00', video_status='ATTACHED',
                                 video_file='evidence/video/EVENT-20260924-00042.mp4', video_has_audio=True,
                                 extra_videos=[{'camera_id': 'CAM-007', 'file': 'x.mp4', 'integrity_hash': 'abc'}],
                                 semantic_analysis={'classification': 'POSIBLE_AUXILIO', 'signals': ['a']},
                                 integrity_hash='f' * 64, voice_event_id='VOICE-1')
        evidence.assessment = object()  # el análisis vivo no se guarda: sólo sus datos
        store.evidence.insert(0, evidence)
        store.voice_events.insert(0, VoiceEvent('VOICE-1', '2026-09-24 10:00:05', 'CAM-008', 'ayuda',
                                                evidence_id='EVENT-20260924-00042'))
        store.voice_events.insert(0, VoiceEvent('VOICE-ORDINARIA', '2026-09-24 10:01:00', 'CAM-008',
                                                'vamos por un café', classification='NORMAL'))
        store.candidate_matches.insert(0, CandidateMatch(
            'CM-TEST', 'BUS-2026-0999', 'SP-X', 'CAM-008', '2026-09-24 10:00:00',
            signals={'face': MatchSignal('ALTA', 'parecido', .71), 'route': MatchSignal()},
            capture_kind='EVENTO', capture_attributes={'estimated_age': 29}, relevance_score=.8))
        store.track_sightings.insert(0, TrackSighting('SGT-1', 'EVENT-20260924-00042', 'PC-1', 'PERSON-TRACK-A',
                                                      'CAM-007', '2026-09-24 10:03:00', .6, 'ALTA'))
        store.logs.insert(0, AuditLog('2026-09-24 10:00:06', 'Sistema', 'Evidencia', 'EVENT-20260924-00042 creado'))
        store.settings['Cámaras']['Intervalo de actualización (s)'] = 42
        store.phrases.append('socorro')
        next(u for u in store.users if u.id == 'USR-02').status = 'Suspendido'

    def test_everything_needed_for_review_survives_a_restart(self):
        database = LocalDatabase(self.path)
        database.load()
        self.record_everything()
        self.assertGreater(database.save(), 0)

        self.restart()
        case = next(c for c in store.cases if c.id == 'BUS-2026-0999')
        self.assertIsInstance(case.person, Person)
        self.assertEqual((case.person.clothing, case.location), ('Sudadera roja', 'Macroplaza'))
        detection = store.detections[0]
        self.assertEqual((detection.id, detection.clothing_color, len(detection.embedding)), ('DET-900', 'rojo', 512))
        evidence = store.evidence[0]
        self.assertEqual((evidence.event_id, evidence.trigger_timestamp, evidence.video_has_audio),
                         ('EVENT-20260924-00042', '2026-09-24 10:00:00', True))
        self.assertIsNone(evidence.assessment)
        self.assertEqual(evidence.extra_videos[0]['camera_id'], 'CAM-007')
        candidate = store.candidate_matches[0]
        self.assertIsInstance(candidate.signal('face'), MatchSignal)
        self.assertEqual((candidate.signal('face').level, candidate.capture_kind), ('ALTA', 'EVENTO'))
        self.assertEqual(store.track_sightings[0].camera_id, 'CAM-007')
        self.assertEqual([v.id for v in store.voice_events], ['VOICE-1'])  # la charla ordinaria no se guardó
        self.assertEqual(store.logs[0].description, 'EVENT-20260924-00042 creado')
        self.assertEqual(store.settings['Cámaras']['Intervalo de actualización (s)'], 42)
        self.assertIn('socorro', store.phrases)
        self.assertEqual(next(u for u in store.users if u.id == 'USR-02').status, 'Suspendido')

    def test_demo_records_are_updated_in_place_and_order_is_kept(self):
        database = LocalDatabase(self.path)
        database.load()
        store.detections[0].status = 'Descartada'
        order = [d.id for d in store.detections]
        database.save()
        self.restart()
        self.assertEqual([d.id for d in store.detections], order)
        self.assertEqual(store.detections[0].status, 'Descartada')
        self.assertEqual(len({d.id for d in store.detections}), len(store.detections))  # sin duplicados

    def test_only_what_changed_is_written(self):
        database = LocalDatabase(self.path)
        database.load()
        self.assertGreater(database.save(), 0)
        self.assertEqual(database.save(), 0)
        store.cases[0].status = 'Pausada'
        self.assertEqual(database.save(), 1)

    def test_what_the_application_drops_is_dropped_from_the_database(self):
        from models.alert_import_record import AlertImportRecord
        database = LocalDatabase(self.path)
        database.load()
        store.imports.insert(0, AlertImportRecord('ALERT-TEMP'))
        database.save()
        store.imports.clear()  # importación cancelada
        database.save()
        self.restart()
        self.assertEqual(store.imports, [])

    def test_a_damaged_document_does_not_block_the_rest(self):
        database = LocalDatabase(self.path)
        database.load()
        self.record_everything()
        database.save()
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("UPDATE documentos SET datos = '{no es json' WHERE coleccion = 'detecciones' "
                               "AND clave = 'DET-900'")
            connection.commit()
        finally:
            connection.close()
        self.restart()
        self.assertFalse(any(d.id == 'DET-900' for d in store.detections))
        self.assertTrue(any(e.event_id == 'EVENT-20260924-00042' for e in store.evidence))


if __name__ == '__main__':
    unittest.main()
