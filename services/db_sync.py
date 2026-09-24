"""Persistencia en PostgreSQL de lo que NEXO registra en memoria.

La aplicación trabaja con las listas de services/store.py. Este servicio:
  1. al conectar, crea o actualiza el esquema y carga en memoria los expedientes y
     detecciones guardados en sesiones anteriores (la base de datos manda);
  2. cada pocos segundos guarda los casos, fotografías, cámaras y detecciones que
     cambiaron desde la última vez.

La base de datos es opcional: si el contenedor está apagado la aplicación sigue
funcionando y el servicio vuelve a intentarlo solo.
"""
import logging
import threading
from datetime import date, datetime

import config
from models.detection import Detection
from models.match import Match
from models.person import Person
from models.search_case import SearchCase
from services import store

logger = logging.getLogger(__name__)

UNKNOWN = ('desconocida', 'desconocido', 'no especificado', 'sin información', '')


# ---------------------------------------------------------------------- conversions
def to_int(text):
    try:
        return int(str(text).strip().split()[0])
    except (ValueError, IndexError):
        return None


def to_date(text):
    try:
        return date.fromisoformat(str(text).strip()[:10])
    except ValueError:
        return None


def to_timestamp(text):
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(text).strip(), fmt)
        except ValueError:
            continue
    return None


def or_unknown(value, unknown='Desconocido'):
    if value is None or value == '':
        return unknown
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    return str(value)


def case_row(case):
    p = case.person
    return (case.id, p.name, to_int(p.age), p.sex, p.height, p.build, p.skin, p.hair, p.eyes, p.clothing,
            p.marks, p.description, to_date(case.missing_date), case.missing_time, case.location, case.zone,
            case.status, case.owner, to_timestamp(case.reported_at), case.reference_status)


def camera_row(camera):
    return (camera.id, camera.name, camera.location, camera.zone, camera.status, camera.last_seen)


def detection_row(detection, match):
    return (detection.id, detection.case_id, detection.camera_id, to_timestamp(detection.timestamp),
            detection.similarity, detection.quality, detection.status, detection.capture,
            match.id if match else None, match.reviewed_by if match else None,
            match.reviewed_at if match else None)


# ---------------------------------------------------------------------- service
class DatabaseSync:
    def __init__(self):
        self.status = 'DESCONECTADA'  # DESCONECTADA · SINCRONIZADA · ERROR
        self.error = None
        self.last_sync = None
        self._ready = False
        self._seen = {}  # ('case'|'photos'|'camera'|'detection', key) -> last saved row
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='db-sync', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        try:
            self.sync_once()  # lo último que cambió antes de cerrar
        except Exception:
            pass

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.sync_once()
            except Exception as error:  # la aplicación sigue; se reintenta en el siguiente ciclo
                if self.status != 'ERROR' or str(error) != self.error:
                    logger.warning('Base de datos: %s', error)
                self._ready, self.status, self.error = False, 'ERROR', str(error)
            self._stop.wait(config.DB_SYNC_SECONDS)

    def sync_once(self):
        from services.db_service import database_available, get_db_connection
        if not database_available():
            self._ready, self.status = False, 'DESCONECTADA'
            self.error = 'El contenedor de PostgreSQL no responde (docker compose up -d).'
            return False
        with self._lock:
            if not self._ready:
                from services.db_bootstrap import initialize_database
                initialize_database()
                self._seen.clear()
                with get_db_connection() as conn:
                    self._load(conn)
                self._ready = True
                logger.info('Base de datos conectada: expedientes cargados en memoria')
            with get_db_connection() as conn:
                self._save(conn)
            self.status, self.error, self.last_sync = 'SINCRONIZADA', None, store.now()
        return True

    # ------------------------------------------------------------------ load
    def _load(self, conn):
        """Los expedientes y detecciones guardados vuelven a la aplicación al arrancar."""
        with conn.cursor() as cur:
            cur.execute('''SELECT id, folio, nombre_completo, edad, sexo, estatura, complexion, tez, cabello, ojos,
                                  vestimenta, senas_particulares, descripcion_fisica, fecha_desaparicion,
                                  hora_desaparicion, lugar_desaparicion, zona, estado, responsable, fecha_reporte,
                                  estado_referencia
                           FROM personas WHERE folio IS NOT NULL ORDER BY folio''')
            people = cur.fetchall()
            cur.execute('SELECT persona_id, ruta_imagen FROM fotografias_persona ORDER BY persona_id, orden, id')
            photos = {}
            for person_id, path in cur.fetchall():
                photos.setdefault(person_id, []).append(path)
            cur.execute('''SELECT codigo, folio, codigo_camara, fecha_hora, similitud, calidad, estado, captura,
                                  coincidencia_codigo, revisado_por, revisado_en
                           FROM detecciones ORDER BY fecha_hora NULLS FIRST, codigo''')
            detections = cur.fetchall()
        by_id = {case.id: case for case in store.cases}
        for (pid, folio, name, age, sex, height, build, skin, hair, eyes, clothing, marks, description, missing,
             missing_time, location, zone, status, owner, reported, reference) in people:
            person = Person(name=name, age=or_unknown(age, 'Desconocida'), sex=or_unknown(sex),
                            height=or_unknown(height, 'Desconocida'), build=or_unknown(build, 'Desconocida'),
                            skin=or_unknown(skin), hair=or_unknown(hair), eyes=or_unknown(eyes),
                            clothing=or_unknown(clothing, 'Sin información'), marks=or_unknown(marks, 'Sin información'),
                            description=description or '', photos=photos.get(pid, []))
            case = SearchCase(folio, person, or_unknown(missing, 'Desconocida'),
                              or_unknown(reported, store.now()), or_unknown(location, 'Desconocida'),
                              or_unknown(zone, 'Sin zona'), or_unknown(owner, 'Sistema'),
                              status=status or 'En búsqueda', missing_time=or_unknown(missing_time, 'Desconocida'),
                              reference_status=or_unknown(reference, 'Pendiente de procesamiento'))
            if folio in by_id:  # expediente de demostración ya en memoria: se actualiza
                current = by_id[folio]
                current.__dict__.update({k: v for k, v in case.__dict__.items() if k != 'person'})
                current.person.__dict__.update(person.__dict__)
            else:
                store.cases.append(case)
        known = {d.id for d in store.detections}
        known_matches = {m.id for m in store.matches}
        for (code, folio, camera, when, similarity, quality, status, capture, match_code, reviewer,
             reviewed_at) in detections:
            if code in known:
                current = next(d for d in store.detections if d.id == code)
                current.status = status or current.status
                continue
            store.detections.insert(0, Detection(code, folio, camera, or_unknown(when, store.now()), similarity or 0,
                                                 status=status or 'Pendiente de validación',
                                                 quality=quality or 'Adecuada',
                                                 capture=capture or '/assets/demo/capture.svg'))
            if match_code and match_code not in known_matches:
                store.matches.insert(0, Match(match_code, code, status or 'Pendiente de validación',
                                              reviewer or '', reviewed_at or ''))
        for match in store.matches:  # revisiones hechas en sesiones anteriores
            detection = next((d for d in store.detections if d.id == match.detection_id), None)
            if detection and detection.status != match.status and detection.status != 'Pendiente de validación':
                match.status = detection.status

    # ------------------------------------------------------------------ save
    def _changed(self, kind, key, row):
        if self._seen.get((kind, key)) == row:
            return False
        self._seen[(kind, key)] = row
        return True

    def _save(self, conn):
        with conn.cursor() as cur:
            for camera in list(store.cameras):
                row = camera_row(camera)
                if self._changed('camera', camera.id, row):
                    cur.execute('''INSERT INTO camaras (codigo_camara, nombre, ubicacion, zona, estado, ultima_comunicacion)
                                   VALUES (%s, %s, %s, %s, %s, %s)
                                   ON CONFLICT (codigo_camara) DO UPDATE SET nombre = EXCLUDED.nombre,
                                       ubicacion = EXCLUDED.ubicacion, zona = EXCLUDED.zona,
                                       estado = EXCLUDED.estado, ultima_comunicacion = EXCLUDED.ultima_comunicacion''',
                                row)
            for case in list(store.cases):
                row = case_row(case)
                if self._changed('case', case.id, row):
                    cur.execute('''INSERT INTO personas (folio, nombre_completo, edad, sexo, estatura, complexion, tez,
                                       cabello, ojos, vestimenta, senas_particulares, descripcion_fisica,
                                       fecha_desaparicion, hora_desaparicion, lugar_desaparicion, zona, estado,
                                       responsable, fecha_reporte, estado_referencia)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                   ON CONFLICT (folio) DO UPDATE SET nombre_completo = EXCLUDED.nombre_completo,
                                       edad = EXCLUDED.edad, sexo = EXCLUDED.sexo, estatura = EXCLUDED.estatura,
                                       complexion = EXCLUDED.complexion, tez = EXCLUDED.tez,
                                       cabello = EXCLUDED.cabello, ojos = EXCLUDED.ojos,
                                       vestimenta = EXCLUDED.vestimenta,
                                       senas_particulares = EXCLUDED.senas_particulares,
                                       descripcion_fisica = EXCLUDED.descripcion_fisica,
                                       fecha_desaparicion = EXCLUDED.fecha_desaparicion,
                                       hora_desaparicion = EXCLUDED.hora_desaparicion,
                                       lugar_desaparicion = EXCLUDED.lugar_desaparicion, zona = EXCLUDED.zona,
                                       estado = EXCLUDED.estado, responsable = EXCLUDED.responsable,
                                       fecha_reporte = EXCLUDED.fecha_reporte,
                                       estado_referencia = EXCLUDED.estado_referencia, updated_at = NOW()''',
                                row)
                photos = tuple(case.person.photos)
                if self._changed('photos', case.id, photos):
                    cur.execute('SELECT id FROM personas WHERE folio = %s', (case.id,))
                    person_id = cur.fetchone()[0]
                    cur.execute('DELETE FROM fotografias_persona WHERE persona_id = %s', (person_id,))
                    for order, photo in enumerate(photos):
                        cur.execute('''INSERT INTO fotografias_persona (persona_id, ruta_imagen, tipo, orden)
                                       VALUES (%s, %s, 'referencia', %s)''', (person_id, photo, order))
            matches = {m.detection_id: m for m in list(store.matches)}
            for detection in list(store.detections):
                row = detection_row(detection, matches.get(detection.id))
                if self._changed('detection', detection.id, row):
                    cur.execute('''INSERT INTO detecciones (codigo, persona_id, folio, id_camara, codigo_camara,
                                       fecha_hora, similitud, calidad, estado, captura, coincidencia_codigo,
                                       revisado_por, revisado_en)
                                   SELECT %s, (SELECT id FROM personas WHERE folio = %s), %s,
                                          (SELECT id FROM camaras WHERE codigo_camara = %s), %s,
                                          %s, %s, %s, %s, %s, %s, %s, %s
                                   ON CONFLICT (codigo) DO UPDATE SET estado = EXCLUDED.estado,
                                       similitud = EXCLUDED.similitud, calidad = EXCLUDED.calidad,
                                       captura = EXCLUDED.captura, coincidencia_codigo = EXCLUDED.coincidencia_codigo,
                                       revisado_por = EXCLUDED.revisado_por, revisado_en = EXCLUDED.revisado_en,
                                       updated_at = NOW()''',
                                (row[0], row[1], row[1], row[2], row[2], *row[3:]))
        conn.commit()


database = DatabaseSync()
