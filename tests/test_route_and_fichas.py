"""Trayecto en el mapa y comparación de capturas contra fichas de búsqueda.

Trayecto: los puntos donde se vio a alguien se unen en orden; cada tramo dice si era posible a
pie, en vehículo o no era posible en ese tiempo, y la última posición queda marcada.
Fichas: una persona vista en un evento se compara sola contra todas las fichas activas; la
comparación considera el rostro, la fecha de desaparición, la distancia real y los rasgos
visibles, y nada de eso descarta a nadie ni afirma una identidad.
"""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import numpy as np

import config
from models.detection import Detection
from models.event_frame import DetectedPersonCandidate
from models.evidence_event import EvidenceEvent
from models.search_profile import SearchProfile
from services import store
from services.geo_service import bearing, camera_position, haversine_km, resolve_place
from services.cameras_service import get_camera

CASE = 'BUS-2026-0184'


def unit(*values):
    vector = np.zeros(512, dtype=np.float32)
    vector[:len(values)] = values
    return [float(v) for v in vector / np.linalg.norm(vector)]


class StoreSnapshot(unittest.TestCase):
    NAMES = ('detections', 'matches', 'logs', 'evidence', 'person_candidates', 'track_sightings',
             'search_profiles', 'candidate_matches', 'cases')

    def setUp(self):
        self.saved = {name: getattr(store, name)[:] for name in self.NAMES}
        self.addCleanup(lambda: [getattr(store, name).__setitem__(slice(None), value)
                                 for name, value in self.saved.items()])
        # Semillas frescas: otras pruebas descartan o validan detecciones de la demo y dejan
        # personas de eventos en memoria.
        from mocks.cases import seed_cases
        from mocks.detections import seed_detections, seed_matches
        fresh = {'cases': seed_cases(), 'detections': seed_detections(), 'matches': seed_matches()}
        for name in self.NAMES:
            if name != 'logs':
                getattr(store, name)[:] = fresh.get(name, [])


class GeoTest(unittest.TestCase):
    def test_real_distances_and_headings(self):
        self.assertAlmostEqual(haversine_km((19.4326, -99.1332), (25.6866, -100.3161)), 706, delta=10)
        self.assertAlmostEqual(bearing((0, 0), (1, 0)), 0, delta=.1)  # hacia el norte
        self.assertAlmostEqual(bearing((0, 0), (0, 1)), 90, delta=.1)  # hacia el este

    def test_the_team_cameras_are_a_few_steps_apart(self):
        positions = [camera_position(get_camera(cid)) for cid in
                     (config.DEFAULT_CAMERA_ID, config.SECOND_CAMERA_ID, config.THIRD_CAMERA_ID)]
        for a in positions:
            for b in positions:
                self.assertLess(haversine_km(a, b), .5)

    def test_places_resolve_offline_or_stay_unknown(self):
        self.assertEqual(resolve_place('Plaza del Reloj, centro')[2], 'CAM-016 · Plaza del Reloj')
        self.assertEqual(resolve_place('Col. Centro, Guadalajara, Jalisco')[2], 'Guadalajara')
        self.assertIsNone(resolve_place('un lugar que no está en el catálogo'))
        self.assertIsNone(resolve_place(''))


class RouteTest(StoreSnapshot):
    def test_the_seeded_case_walks_between_the_team_cameras(self):
        from services.route_service import case_route
        route = case_route(CASE)
        self.assertEqual([p.camera_id for p in route.points], ['CAM-004', 'CAM-007', 'CAM-008'])
        self.assertEqual(route.last_point.camera_id, 'CAM-008')
        self.assertEqual(route.last_point.last_seen, '2026-09-23 10:25:41')
        self.assertTrue(all(leg.plausibility == 'A_PIE' for leg in route.legs))
        self.assertEqual(route.warnings, [])
        self.assertTrue(route.next_cameras)  # dónde seguir buscando

    def test_consecutive_sightings_at_one_camera_are_one_stop(self):
        from services.route_service import case_route
        store.detections.insert(0, Detection('DET-X1', CASE, 'CAM-008', '2026-09-23 10:27:00', 90))
        route = case_route(CASE)
        self.assertEqual(len(route.points), 3)
        self.assertEqual(route.last_point.observations, 2)
        self.assertEqual(route.last_point.last_seen, '2026-09-23 10:27:00')

    def test_discarded_detections_leave_the_route(self):
        from services.route_service import case_route
        next(d for d in store.detections if d.id == 'DET-003').status = 'Descartada'
        self.addCleanup(lambda: setattr(next(d for d in store.detections if d.id == 'DET-003'), 'status',
                                        'Pendiente de validación'))
        self.assertEqual(case_route(CASE).last_point.camera_id, 'CAM-007')

    def test_an_impossible_jump_is_flagged_not_hidden(self):
        from services.route_service import case_route, route_payload
        # 900 km en cuatro minutos: una de las dos detecciones tiene que ser un falso positivo.
        store.detections.insert(0, Detection('DET-X2', CASE, 'CAM-001', '2026-09-23 10:29:41', 80))
        route = case_route(CASE)
        self.assertEqual(route.legs[-1].plausibility, 'NO_PLAUSIBLE')
        self.assertTrue(route.warnings and 'falso positivo' in route.warnings[0])
        payload = route_payload(route)
        self.assertEqual(payload['legs'][-1]['mode'], 'none')  # sin trazo por calles: línea recta
        self.assertEqual(payload['last']['camera'], 'CAM-001')

    def test_validated_points_are_marked(self):
        from services.route_service import case_route, route_payload
        detection = next(d for d in store.detections if d.id == 'DET-001')
        detection.status = 'Validada por operador'
        self.addCleanup(lambda: setattr(detection, 'status', 'Pendiente de validación'))
        route = case_route(CASE)
        self.assertEqual(route.points[0].status, 'VALIDADA')
        self.assertEqual(route.last_validated.camera_id, 'CAM-004')
        self.assertTrue(route_payload(route)['legs'][0]['possible'])  # el otro extremo sigue pendiente

    def test_plausibility_thresholds(self):
        from services.route_service import plausibility
        self.assertEqual(plausibility(.01, 5)[0], 'MISMO_LUGAR')
        self.assertEqual(plausibility(.3, 4)[0], 'A_PIE')
        self.assertEqual(plausibility(40, 45)[0], 'VEHICULO')
        self.assertEqual(plausibility(700, 20)[0], 'NO_PLAUSIBLE')
        self.assertEqual(plausibility(5, 0)[0], 'NO_PLAUSIBLE')

    def test_a_person_from_an_event_is_followed_across_cameras(self):
        from services.route_service import event_track_route
        from services.tracking_service import open_event_tracking, record_sighting, watch_targets
        now = datetime.now()
        store.evidence.insert(0, EvidenceEvent('EVENT-RUTA-1', 'CAM-008', 'Pasillo B',
                                               now.strftime('%Y-%m-%d %H:%M:%S'), 'POSIBLE_AUXILIO', 'MEDIA',
                                               trigger_timestamp=(now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')))
        candidate = DetectedPersonCandidate('PC-RUTA', 'EVENT-RUTA-1', 'CAM-008', store.now(),
                                            person_track_id='PERSON-TRACK-A', face_embedding=unit(1, 0))
        store.person_candidates.append(candidate)
        self.assertEqual(watch_targets(), [])  # sin seguimiento abierto no se busca a nadie
        open_event_tracking('EVENT-RUTA-1')
        self.assertEqual([c.candidate_id for c, _ in watch_targets()], ['PC-RUTA'])
        with patch('config.TRACK_SIGHTING_COOLDOWN_SECONDS', 0):
            self.assertIsNotNone(record_sighting(candidate, 'CAM-007', .62, 'ALTA'))
        route = event_track_route('EVENT-RUTA-1', 'PC-RUTA')
        self.assertEqual([p.status for p in route.points], ['EVENTO', 'AVISTAMIENTO'])
        self.assertEqual(route.last_point.camera_id, 'CAM-007')

    def test_a_false_positive_stops_the_tracking(self):
        from services.tracking_service import open_event_tracking, watch_targets
        event = EvidenceEvent('EVENT-RUTA-2', 'CAM-008', 'Pasillo B', store.now(), 'POSIBLE_AUXILIO', 'MEDIA')
        store.evidence.insert(0, event)
        store.person_candidates.append(DetectedPersonCandidate('PC-FP', 'EVENT-RUTA-2', 'CAM-008', store.now(),
                                                               face_embedding=unit(1, 0)))
        open_event_tracking('EVENT-RUTA-2')
        self.assertTrue(watch_targets())
        event.review_status = 'FALSO_POSITIVO'
        self.assertEqual(watch_targets(), [])

    def test_live_recognition_records_a_sighting_of_a_tracked_person(self):
        from services import face_engine
        from services.live_recognition_service import LiveRecognition
        from services.tracking_service import get_track_sightings
        candidate = DetectedPersonCandidate('PC-LIVE', 'EVENT-RUTA-3', 'CAM-008', store.now(),
                                            person_track_id='PERSON-TRACK-B', face_embedding=unit(0, 1))
        live = LiveRecognition(camera_id='CAM-007')
        live.watchlist = [(candidate, candidate.face_embedding)]
        face = face_engine.FaceResult(bbox=(100, 80, 220, 230), det_score=.9,
                                      embedding=np.asarray(unit(0, 1), dtype=np.float32))
        found = live._identify(face)
        self.assertEqual((found['track'], found['track_level']), (candidate, 'ALTA'))
        with patch('config.TRACK_SIGHTING_COOLDOWN_SECONDS', 0):
            live._record_sighting(np.full((480, 640, 3), 90, dtype=np.uint8), found)
        self.assertEqual([s.camera_id for s in get_track_sightings('PC-LIVE')], ['CAM-007'])


class AppearanceTest(unittest.TestCase):
    def test_declared_colors_prefer_the_upper_garment(self):
        from services.appearance_service import declared_colors
        self.assertEqual(declared_colors('Chaqueta azul, pantalón oscuro y calzado blanco.'), ['azul'])
        self.assertEqual(declared_colors('Vestía de negro'), ['negro'])
        self.assertEqual(declared_colors('Sin información'), [])

    def test_the_torso_color_is_estimated_below_the_face(self):
        from services.appearance_service import upper_clothing_color
        frame = np.full((480, 640, 3), 235, dtype=np.uint8)
        frame[260:470, 180:420] = (170, 60, 20)  # BGR: azul
        self.assertEqual(upper_clothing_color(frame, (250, 90, 350, 220)), 'azul')
        self.assertIsNone(upper_clothing_color(frame[:230], (250, 90, 350, 220)))  # torso fuera de cuadro

    def test_traits_never_discard(self):
        from services.appearance_service import age_compatibility, clothing_compatibility
        self.assertEqual(clothing_compatibility('Chaqueta azul', 'azul')[0], 'MEDIA')
        self.assertEqual(clothing_compatibility('Chaqueta azul', 'rojo')[0], 'BAJA')
        self.assertEqual(clothing_compatibility('', 'rojo')[0], 'NO_EVALUABLE')
        self.assertEqual(age_compatibility('24', 27)[0], 'MEDIA')
        self.assertEqual(age_compatibility('24', 50)[0], 'BAJA')
        self.assertEqual(age_compatibility('Desconocida', 27)[0], 'NO_EVALUABLE')


class FichaMatchingTest(StoreSnapshot):
    def setUp(self):
        super().setUp()
        self.ready = patch('services.face_engine.ready', return_value=True)
        self.ready.start()
        self.addCleanup(self.ready.stop)
        # La ficha de Elena Robles con una huella (en la demo sus fotos son ilustraciones).
        self.profile = SearchProfile('SP-TEST', CASE, store.now(), 'Operador01', face_embedding=unit(1, 0))
        from services.search_matching_service import _fill_from_declared
        case = next(c for c in store.cases if c.id == CASE)
        _fill_from_declared(self.profile, case.missing_date, case.missing_time, 'Tec de Nuevo León',
                            case.person.age, clothing=case.person.clothing)
        store.search_profiles.insert(0, self.profile)

    def event_person(self, embedding, candidate_id='PC-MATCH', camera='CAM-008', age=None, color=None):
        candidate = DetectedPersonCandidate(candidate_id, 'EVENT-FICHA-1', camera, '2026-09-23 11:00:00',
                                            person_track_id='PERSON-TRACK-A', face_embedding=embedding,
                                            estimated_age=age, clothing_color=color)
        store.person_candidates.append(candidate)
        return candidate

    def test_a_discarded_detection_does_not_return_through_its_candidate(self):
        # BUSCAR también crea candidatos de las detecciones del propio caso. Si después el
        # operador descarta una en /matches, tampoco vuelve al mapa por su candidato.
        from services.route_service import case_route
        from services.search_matching_service import get_candidates, run_search
        run_search(CASE, actor='Operador01')
        self.assertTrue(any(c.detection_id == 'DET-003' for c in get_candidates(CASE)))
        next(d for d in store.detections if d.id == 'DET-003').status = 'Descartada'
        route = case_route(CASE)
        self.assertEqual(route.last_point.camera_id, 'CAM-007')
        self.assertEqual(len(route.points), 2)

    def test_people_seen_in_an_event_are_compared_with_every_active_ficha(self):
        from services.search_matching_service import get_candidates, match_event_candidates
        self.event_person(unit(1, .1), age=26, color='azul')
        self.event_person(unit(0, 1), candidate_id='PC-OTHER')  # nadie parecido
        created = match_event_candidates('EVENT-FICHA-1')
        self.assertEqual([c.person_candidate_id for c in created], ['PC-MATCH'])
        candidate = created[0]
        self.assertEqual((candidate.case_id, candidate.capture_kind, candidate.status),
                         (CASE, 'EVENTO', 'PENDING_HUMAN_REVIEW'))
        self.assertTrue(candidate.linked_to_distress_event)
        self.assertEqual(candidate.signal('face').level, 'ALTA')
        self.assertEqual(candidate.signal('appearance').level, 'MEDIA')  # ropa azul y edad compatibles
        self.assertEqual(candidate.capture_attributes['clothing_color'], 'azul')
        self.assertEqual(get_candidates(event_id='EVENT-FICHA-1'), created)
        self.assertEqual(match_event_candidates('EVENT-FICHA-1'), [])  # no se duplica

    def test_distance_and_time_since_the_disappearance_are_weighed_not_used_to_discard(self):
        from services.search_matching_service import _geographic_signal
        near = _geographic_signal(self.profile, get_camera('CAM-008'), datetime(2026, 9, 23, 11))
        far = _geographic_signal(self.profile, get_camera('CAM-011'), datetime(2026, 9, 22, 1))
        self.assertEqual(near.level, 'ALTA')
        self.assertIn('m del último lugar conocido', near.detail)
        self.assertEqual(far.level, 'BAJA')  # Mérida una hora después: difícil, pero no descartado
        self.assertIn('No se descarta', far.detail)

    def test_search_by_ficha_ranks_captures_without_creating_candidates(self):
        from services.search_matching_service import profile_from_reference, search_by_profile
        self.event_person(unit(1, .2), age=25)
        store.detections.insert(0, Detection('DET-EMB', 'BUS-2026-0185', 'CAM-007', '2026-09-23 11:05:00', 70,
                                             embedding=unit(1, .15), estimated_age=24, clothing_color='azul'))
        store.detections.insert(0, Detection('DET-NO', 'BUS-2026-0186', 'CAM-004', '2026-09-23 11:06:00', 70,
                                             embedding=unit(0, 0, 1)))
        before = len(store.candidate_matches)
        reference = profile_from_reference(unit(1, 0), name='Referencia autorizada', age='24',
                                           missing_date='2026-09-22', location='Tec de Nuevo León',
                                           clothing='Chaqueta azul')
        results = search_by_profile(reference, include_database=False)
        self.assertEqual({r['capture'].capture_id for r in results}, {'PC-MATCH', 'DET-EMB'})
        self.assertTrue(all(r['similarity'] >= config.FACE_MATCH_THRESHOLD for r in results))
        self.assertEqual(len(store.candidate_matches), before)  # consultar no es proponer

    def test_a_new_ficha_looks_back_at_what_the_cameras_already_saw(self):
        from services.search_matching_service import retro_search_new_case
        self.event_person(unit(1, .1))
        created = retro_search_new_case(CASE)
        self.assertEqual([c.person_candidate_id for c in created], ['PC-MATCH'])
        self.assertTrue(any('ya registradas por las cámaras' in log.description for log in store.logs))

    def test_detections_carry_their_signals_for_the_side_by_side_view(self):
        from services.search_matching_service import detection_signals
        detection = Detection('DET-SIDE', CASE, 'CAM-008', '2026-09-23 10:30:00', 72, embedding=unit(1, .05),
                              estimated_age=25, clothing_color='azul')
        store.detections.insert(0, detection)
        profile, signals = detection_signals(detection)
        self.assertIs(profile, self.profile)
        self.assertEqual(set(signals), {'face', 'temporal', 'geographic', 'appearance', 'route'})
        self.assertEqual(signals['face'].level, 'ALTA')
        self.assertEqual(signals['route'].level, 'ALTA')  # CAM-007, contigua, minutos antes


if __name__ == '__main__':
    unittest.main()
