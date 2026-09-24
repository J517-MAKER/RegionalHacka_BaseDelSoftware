"""Alert import: OCR reading, editable fields, matching proposals and case creation."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from models.alert_import_record import AlertImportRecord
from services import face_engine, store
from services.alert_import_service import (analyze_alert, cancel_import, compare_with_face_database, context_matches,
                                          create_case_from_alert, detect_type, link_to_case, match_face_reference,
                                          normalize_date, parse_fields, prepare_face_reference, run_matching,
                                          save_upload, score_case, send_to_review, text_matches, update_fields)

# A real poster keeps labels and values on separate lines, and OCR often glues words.
OCR_SAMPLE = '''ALERTA DE BUSQUEDA
FICHADEPERSONADESAPARECIDA
NOMBRECOMPLETO:
ElenaRoblesMartinez
FOLIO:
ALB-2026-0451
EDAD:
24 anos
SEXO:
Mujer
NACIONALIDAD:
Mexicana
FECHADEDESAPARICION:
22deseptiembrede2026
FECHA DEL REPORTE: 23/09/2026
LUGARDELOSHECHOS:
Plaza de la Republica, Centro
COMPLEXION:
Media, estatura 1.65 m, tez clara
SENASPARTICULARES:
Lunar en la mejilla derecha
VESTIMENTA:
Chaqueta azul, pantalon oscuro, calzado blanco
AUTORIDADEMISORA:
Fiscalia General Region Centro
CARPETADEINVESTIGACION:
FGR/CEN/0187/2026'''


def poster_bytes(path, fmt=None):
    """Synthetic search poster: header, portrait block and labelled fields."""
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (1000, 1400), 'white')
    draw = ImageDraw.Draw(image)

    def font(size):
        try:
            return ImageFont.truetype('arial.ttf', size)
        except Exception:
            return ImageFont.load_default(size)
    draw.rectangle([0, 0, 1000, 120], fill=(20, 43, 59))
    draw.text((40, 35), 'ALERTA DE BUSQUEDA', font=font(46), fill='white')
    draw.rectangle([40, 200, 340, 580], fill=(214, 220, 226), outline=(120, 130, 140), width=3)
    draw.ellipse([105, 245, 275, 455], fill=(232, 205, 182), outline=(90, 90, 90))
    draw.ellipse([145, 320, 170, 340], fill=(40, 40, 40))
    draw.ellipse([210, 320, 235, 340], fill=(40, 40, 40))
    y = 210
    for label, value in [('NOMBRE COMPLETO:', 'Elena Robles Martinez'), ('EDAD:', '24 anos'),
                         ('SEXO:', 'Mujer'), ('FECHA DE DESAPARICION:', '22 de septiembre de 2026'),
                         ('LUGAR DE LOS HECHOS:', 'Plaza de la Republica, Centro'),
                         ('VESTIMENTA:', 'Chaqueta azul, pantalon oscuro')]:
        draw.text((380, y), label, font=font(24), fill=(20, 43, 59))
        draw.text((380, y + 32), value, font=font(24), fill=(35, 51, 65))
        y += 90
    image.save(path, fmt) if fmt else image.save(path)
    return Path(path).read_bytes()


def sample_record(**overrides):
    values = dict(id='ALERT-TEST', person_name='Elena Robles Martinez', age='24', sex_reported='No especificado',
                  date_of_disappearance='2026-09-22', location_of_events='Plaza de la República, Centro',
                  clothing_description='Chaqueta azul, pantalón oscuro y calzado blanco',
                  physical_description='Media, estatura 1.65 m', distinctive_marks='Lunar en la mejilla')
    values.update(overrides)
    return AlertImportRecord(**values)


class AlertImportTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = (store.cases[:], store.logs[:], store.imports[:])
        store.imports.clear()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.patches = [patch('config.IMPORT_DIR', root),
                        patch('config.IMPORT_DOCUMENTS_DIR', root / 'documents'),
                        patch('config.IMPORT_PHOTOS_DIR', root / 'photos'),
                        patch('services.alert_import_service.require', return_value='Operador01')]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        store.cases[:], store.logs[:], store.imports[:] = self.snapshot

    # ------------------------------------------------------------------- upload
    def test_upload_in_a_worker_thread_uses_the_given_actor(self):
        """run.io_bound threads cannot read the session, so the page passes the actor."""
        with patch('services.alert_import_service.require',
                   side_effect=RuntimeError('app.storage.user can only be used within a UI context')):
            record_id, path, kind = save_upload(b'\x89PNG\r\n\x1a\n', 'image/png', 'ficha.png', 'Operador01')
        self.assertTrue(path.exists())
        self.assertEqual(kind, 'image/png')

    def test_only_images_and_pdf_within_the_size_limit(self):
        self.assertEqual(detect_type(b'%PDF-1.7 rest'), 'application/pdf')
        self.assertEqual(detect_type(b'\x89PNG\r\n'), 'image/png')
        self.assertEqual(detect_type(b'\xff\xd8\xff\xe0 jfif'), 'image/jpeg')
        self.assertEqual(detect_type(b'RIFF\xac\x01\x00\x00WEBPVP8 '), 'image/webp')
        with self.assertRaises(ValueError):  # RIFF sin marca WEBP, por ejemplo un WAV
            detect_type(b'RIFF\xac\x01\x00\x00WAVEfmt ')
        with self.assertRaises(ValueError):
            detect_type(b'<html>no soy una ficha</html>', 'image/png')
        with self.assertRaises(ValueError):
            save_upload(b'')
        with self.assertRaises(ValueError):
            save_upload(b'\x89PNG' + b'0' * config.IMPORT_MAX_BYTES, 'image/png')
        record_id, path, kind = save_upload(b'\x89PNG\r\n\x1a\n' + b'0' * 10, 'image/png', '../../evil name.png')
        self.assertTrue(record_id.startswith('ALERT-'))
        self.assertEqual(path.name, record_id + '.png')  # the uploaded name is never trusted
        self.assertEqual(kind, 'image/png')

    # -------------------------------------------------------------------- OCR
    def test_labels_and_dates_survive_glued_ocr(self):
        fields = parse_fields(OCR_SAMPLE)
        self.assertEqual(fields['person_name'], 'Elena Robles Martinez')
        self.assertEqual(fields['folio'], 'ALB-2026-0451')
        self.assertEqual(fields['age'], '24')
        self.assertEqual(fields['sex_reported'], 'Mujer')
        self.assertEqual(fields['nationality'], 'Mexicana')
        self.assertEqual(fields['date_of_disappearance'], '2026-09-22')
        self.assertEqual(fields['date_of_report'], '2026-09-23')
        self.assertEqual(fields['location_of_events'], 'Plaza de la Republica, Centro')
        self.assertIn('tez clara', fields['physical_description'])
        self.assertEqual(fields['distinctive_marks'], 'Lunar en la mejilla derecha')
        self.assertIn('Chaqueta azul', fields['clothing_description'])
        self.assertIn('Fiscalia', fields['authority'])
        self.assertEqual(fields['investigation_file'], 'FGR/CEN/0187/2026')

    def test_date_formats(self):
        for text, expected in [('22 de septiembre de 2026', '2026-09-22'), ('22deseptiembrede2026', '2026-09-22'),
                               ('23/09/2026', '2026-09-23'), ('5-1-26', '2026-01-05'), ('2026-09-22', '2026-09-22')]:
            self.assertEqual(normalize_date(text), expected, text)
        self.assertIsNone(normalize_date('fecha desconocida'))

    def test_unreadable_document_falls_back_to_manual_capture(self):
        record_id, path, kind = save_upload(b'\x89PNG\r\n\x1a\n' + b'0' * 40, 'image/png')
        with patch('services.alert_import_service.read_text', return_value=('', 'Tesseract: TesseractNotFoundError')):
            record = analyze_alert(record_id, path, kind)
        self.assertEqual(record.extraction_status, 'SIN_TEXTO_RECONOCIDO')
        self.assertIsNone(record.person_name)
        self.assertIn('manualmente', record.extraction_notes)
        self.assertEqual(record.photo_path, '')

    def test_reads_a_real_poster_end_to_end(self):
        """Uses the OCR engine actually installed; the slowest test of the suite."""
        path = Path(self.directory.name) / 'poster.png'
        content = poster_bytes(path)
        record_id, saved, kind = save_upload(content, 'image/png', 'ficha.png')
        record = analyze_alert(record_id, saved, kind)
        self.assertIn(record.extraction_status, ('EXTRACCION_COMPLETA', 'EXTRACCION_PARCIAL'))
        self.assertIn('Elena', record.person_name or '')
        self.assertEqual(record.date_of_disappearance, '2026-09-22')
        self.assertTrue(record.photo_path and (config.BASE_DIR / record.photo_path).exists())
        self.assertEqual(store.imports[0].id, record.id)

    def test_reads_a_webp_poster(self):
        path = Path(self.directory.name) / 'poster.webp'
        content = poster_bytes(path, 'WEBP')
        record_id, saved, kind = save_upload(content, 'image/webp', 'ficha.webp')
        self.assertEqual(kind, 'image/webp')
        self.assertEqual(saved.suffix, '.webp')
        with patch('services.alert_import_service.read_text',
                   return_value=(OCR_SAMPLE, 'RapidOCR')) as reader:
            record = analyze_alert(record_id, saved, kind)
        self.assertEqual(reader.call_args.args[0], saved)  # el WebP se lee directamente
        self.assertEqual(record.person_name, 'Elena Robles Martinez')
        self.assertEqual(record.source_type, 'image/webp')
        # OpenCV decodifica el WebP y recorta la fotografía del cartel.
        self.assertTrue(record.photo_path and (config.BASE_DIR / record.photo_path).exists())

    # --------------------------------------------------------------- editing
    def test_operator_corrections_are_kept_and_audited(self):
        record = sample_record(id='ALERT-EDIT')
        store.imports.insert(0, record)
        update_fields(record.id, {'person_name': 'Elena Robles', 'age': '25', 'id': 'HACK'})
        self.assertEqual((record.person_name, record.age, record.id), ('Elena Robles', '25', 'ALERT-EDIT'))
        self.assertEqual(record.extraction_status, 'REVISADA_POR_OPERADOR')
        self.assertTrue(any('corregido' in log.description for log in store.logs))

    # --------------------------------------------------------------- matching
    def test_textual_matching_ranks_the_right_case(self):
        results = text_matches(sample_record())
        self.assertEqual(results[0]['case_id'], 'BUS-2026-0184')
        self.assertEqual(results[0]['level'], 'ALTA')
        self.assertIn('coincidencia textual', results[0]['label'])
        self.assertIn('Misma fecha de desaparición', results[0]['reasons'])
        self.assertEqual(text_matches(sample_record(person_name='Zzz Qqq', age='80',
                                                    date_of_disappearance='2019-01-01',
                                                    location_of_events='Otra ciudad lejana',
                                                    clothing_description=None, physical_description=None,
                                                    distinctive_marks=None)), [])

    def test_scores_stay_proposals_not_identities(self):
        case = next(c for c in store.cases if c.id == 'BUS-2026-0184')
        score, reasons = score_case(sample_record(), case)
        self.assertLessEqual(score, 100)
        self.assertGreaterEqual(score, 60)
        self.assertTrue(all(isinstance(reason, str) for reason in reasons))

    def test_context_matching_uses_place_and_date(self):
        results = context_matches(sample_record())
        kinds = {item['kind'] for item in results}
        self.assertEqual(kinds, {'Zona', 'Fecha', 'Cámaras'})
        self.assertTrue(any(item['cameras'] for item in results))
        empty = context_matches(sample_record(location_of_events=None, date_of_disappearance=None))
        self.assertEqual(empty[0]['kind'], 'Contexto')

    def fake_photo(self):
        photo = Path(self.directory.name) / 'photos' / 'face.png'
        photo.parent.mkdir(parents=True, exist_ok=True)
        photo.write_bytes(b'\x89PNG\r\n\x1a\n')
        return photo

    def test_facial_module_is_only_prepared_never_decided(self):
        """Without InsightFace installed the reference is only prepared: no level is assigned."""
        photo = self.fake_photo()
        with patch('services.alert_import_service.face_engine.installed', return_value=False):
            reference = prepare_face_reference(photo)
            self.assertEqual(reference['status'], 'REFERENCIA_PREPARADA')
            result = match_face_reference(reference)
            self.assertEqual(result['status'], 'PENDIENTE_MODULO_FACIAL')
            self.assertTrue(result['mock'])
            self.assertTrue(all(item['result'] == 'Pendiente del módulo facial' for item in result['candidates']))
            self.assertEqual(prepare_face_reference('')['status'], 'SIN_FOTOGRAFIA')
            self.assertEqual(compare_with_face_database('')['candidates'], [])

    def test_facial_engine_outcomes_are_reported_not_invented(self):
        photo = self.fake_photo()
        engine = 'services.alert_import_service.face_engine'
        with patch(f'{engine}.installed', return_value=True), patch(f'{engine}.best_face', return_value=None):
            reference = prepare_face_reference(photo)
        self.assertEqual(reference['status'], 'SIN_ROSTRO_DETECTADO')
        result = match_face_reference(reference)
        self.assertEqual((result['status'], result['candidates']), ('SIN_ROSTRO_DETECTADO', []))
        self.assertFalse(result['mock'])
        with patch(f'{engine}.installed', return_value=True), \
                patch(f'{engine}.best_face', side_effect=face_engine.FaceEngineUnavailable('Falta el modelo facial.')):
            reference = prepare_face_reference(photo)
        self.assertEqual((reference['status'], reference['message']), ('ERROR_MODULO_FACIAL', 'Falta el modelo facial.'))
        self.assertEqual(match_face_reference(reference)['message'], 'Falta el modelo facial.')

    def test_run_matching_keeps_the_real_facial_candidates(self):
        record = sample_record(id='ALERT-FACE', photo_path='imports/photos/face.png')
        store.imports.insert(0, record)
        reference = {'status': 'REFERENCIA_PREPARADA', 'mock': False, 'embedding': [1.0] + [0.0] * 511}
        candidate = {'case_id': 'BUS-2026-0184', 'name': 'Elena Robles (ficticia)', 'similarity': .71,
                     'percent': 71, 'level': 'ALTA', 'label': 'coincidencia facial alta'}
        with patch('services.alert_import_service.prepare_face_reference', return_value=reference), \
                patch('services.facial_service.compare_with_cases', return_value=([candidate], 1)):
            run_matching(record.id)
        self.assertEqual(record.face_reference_status, 'COINCIDENCIAS_FACIALES')
        self.assertEqual(record.face_matches, [candidate])
        self.assertIn('1 caso(s)', record.face_message)

    def test_run_matching_fills_the_three_groups(self):
        record = sample_record(id='ALERT-MATCH')
        store.imports.insert(0, record)
        run_matching(record.id)
        self.assertEqual(record.text_match_status, 'COINCIDENCIAS_ENCONTRADAS')
        self.assertEqual(record.context_match_status, 'ANALIZADO')
        self.assertEqual(record.face_reference_status, 'SIN_FOTOGRAFIA')
        self.assertEqual(record.review_status, 'PENDIENTE_VALIDACION')

    # ------------------------------------------------------------ final actions
    def test_create_case_link_review_and_cancel(self):
        record = sample_record(id='ALERT-FINAL', folio='ALB-2026-0451', authority='Fiscalía Región Centro')
        store.imports.insert(0, record)
        with patch('services.cases_service.require', return_value='Operador01'):
            case = create_case_from_alert(record.id)
            self.assertEqual(case.person.name, 'Elena Robles Martinez')
            self.assertEqual(case.location, 'Plaza de la República, Centro')
            self.assertIn('ALB-2026-0451', case.person.description)
            self.assertEqual(record.linked_case_id, case.id)
            self.assertEqual(record.review_status, 'CASO_CREADO')
            with self.assertRaises(ValueError):
                create_case_from_alert(record.id)
            with self.assertRaises(ValueError):  # linked alerts cannot be cancelled
                cancel_import(record.id)

        second = sample_record(id='ALERT-LINK')
        store.imports.insert(0, second)
        link_to_case(second.id, 'BUS-2026-0184')
        self.assertEqual((second.linked_case_id, second.review_status), ('BUS-2026-0184', 'VINCULADA_A_CASO'))
        with self.assertRaises(ValueError):
            link_to_case(second.id, 'BUS-9999-0000')

        third = sample_record(id='ALERT-REVIEW')
        store.imports.insert(0, third)
        send_to_review(third.id, 'Falta confirmar la fecha')
        self.assertEqual((third.review_status, third.review_notes), ('EN_REVISION', 'Falta confirmar la fecha'))
        self.assertTrue(any('creado desde la alerta importada' in log.description.lower() for log in store.logs))

    def test_cancel_removes_temporary_files(self):
        record_id, path, kind = save_upload(b'\x89PNG\r\n\x1a\n' + b'0' * 30, 'image/png')
        with patch('services.alert_import_service.read_text', return_value=('', 'sin OCR')):
            record = analyze_alert(record_id, path, kind)
        self.assertTrue(path.exists())
        cancel_import(record.id)
        self.assertFalse(path.exists())
        self.assertNotIn(record, store.imports)
        self.assertTrue(any('cancelada' in log.description for log in store.logs))

    def test_permission_is_enforced_in_the_service(self):
        with patch('services.alert_import_service.require',
                   side_effect=PermissionError('El rol de esta sesión no permite esta operación.')):
            for call in (lambda: save_upload(b'\x89PNG\r\n\x1a\n'),
                         lambda: update_fields('ALERT-X', {}),
                         lambda: run_matching('ALERT-X'),
                         lambda: create_case_from_alert('ALERT-X'),
                         lambda: cancel_import('ALERT-X')):
                with self.assertRaises(PermissionError):
                    call()


if __name__ == '__main__':
    unittest.main()
