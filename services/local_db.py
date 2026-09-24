"""Base de datos local (SQLite): NEXO recuerda lo que registró aunque se reinicie, sin Docker.

Archivo: data/nexo.db (la carpeta data/ está excluida de git). No necesita instalar nada:
SQLite viene con Python. Guarda como documentos JSON los expedientes, detecciones,
coincidencias, evidencias de auxilio, fotos de eventos, personas vistas en eventos, perfiles de
búsqueda, candidatos, reapariciones, solicitudes de eliminación, alertas, importaciones de
fichas, usuarios y preferencias, además de la bitácora completa.

Cómo trabaja: al arrancar carga lo guardado sobre los datos de demostración (la base manda) y
cada pocos segundos guarda sólo lo que cambió. PostgreSQL (docker-compose.yml) sigue siendo
opcional para compartir entre instancias del equipo; esta base no lo necesita ni lo reemplaza.
Los archivos de evidencia (WAV, MP4, JPG) ya viven en evidence/ y no se copian aquí.
"""
import hashlib
import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
import config
from services import store

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    coleccion TEXT NOT NULL,
    clave TEXT NOT NULL,
    datos TEXT NOT NULL,
    huella TEXT NOT NULL,
    posicion INTEGER NOT NULL DEFAULT 0,
    actualizado TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (coleccion, clave)
);
CREATE TABLE IF NOT EXISTS bitacora (
    clave_unica TEXT PRIMARY KEY,
    fecha_hora TEXT NOT NULL,
    usuario TEXT NOT NULL,
    tipo TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    caso_id TEXT,
    camara_id TEXT,
    resultado TEXT,
    dispositivo TEXT
);
CREATE INDEX IF NOT EXISTS bitacora_fecha_idx ON bitacora (fecha_hora DESC);
"""


def enabled():
    """Activa por defecto; nunca durante las pruebas (usan su propio almacén en memoria)."""
    return config.LOCAL_DB_ENABLED and 'PYTEST_CURRENT_TEST' not in os.environ


# ------------------------------------------------------------------ serialización
def to_jsonable(value):
    """Dataclasses, listas y diccionarios a JSON; números de numpy a números de Python."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, 'item'):  # numpy
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if hasattr(value, 'tolist'):
        return value.tolist()
    return str(value)


@dataclass
class Collection:
    name: str
    attribute: str  # lista de services/store.py
    key: str
    cls: type
    exclude: tuple = ()  # campos que no se guardan (objetos de análisis, datos transitorios)
    nested: dict = field(default_factory=dict)  # campo -> clase de su dataclass
    nested_values: dict = field(default_factory=dict)  # campo dict -> clase de sus valores
    keep: object = None  # filtro: qué elementos de la lista merecen guardarse

    def items(self):
        """Lo que se guarda: sin repetir clave (se conserva la primera, la más reciente)."""
        values, seen = [], set()
        for item in list(getattr(store, self.attribute)):
            key = getattr(item, self.key)
            if key in seen or (self.keep is not None and not self.keep(item)):
                continue
            seen.add(key)
            values.append(item)
        return values

    def encode(self, item):
        data = {f.name: to_jsonable(getattr(item, f.name)) for f in fields(item) if f.name not in self.exclude}
        return json.dumps(data, ensure_ascii=False, sort_keys=True)

    def decode(self, text):
        data = json.loads(text)
        names = {f.name for f in fields(self.cls)}
        values = {k: v for k, v in data.items() if k in names}
        for name, nested_cls in self.nested.items():
            if isinstance(values.get(name), dict):
                nested_names = {f.name for f in fields(nested_cls)}
                values[name] = nested_cls(**{k: v for k, v in values[name].items() if k in nested_names})
        for name, nested_cls in self.nested_values.items():
            if isinstance(values.get(name), dict):
                nested_names = {f.name for f in fields(nested_cls)}
                values[name] = {k: nested_cls(**{a: b for a, b in v.items() if a in nested_names})
                                for k, v in values[name].items() if isinstance(v, dict)}
        return self.cls(**values)


def _voice_event_worth_keeping(event):
    """Sólo los eventos de voz que sostienen una alerta o una evidencia: la conversación
    ordinaria nunca se guarda."""
    return bool(event.evidence_id) or any(a.voice_event_id == event.id for a in store.alerts)


def collections():
    from models.alert import EmergencyAlert
    from models.alert_import_record import AlertImportRecord
    from models.candidate_match import CandidateMatch, MatchSignal
    from models.deletion_request import DeletionRequest
    from models.detection import Detection
    from models.event_frame import DetectedPersonCandidate, EventFrame
    from models.evidence_event import EvidenceEvent
    from models.match import Match
    from models.person import Person
    from models.search_case import SearchCase
    from models.search_profile import SearchProfile
    from models.track_sighting import TrackSighting
    from models.user import User
    from models.voice_event import VoiceEvent
    return [
        Collection('casos', 'cases', 'id', SearchCase, nested={'person': Person}),
        Collection('detecciones', 'detections', 'id', Detection),
        Collection('coincidencias', 'matches', 'id', Match),
        Collection('evidencias', 'evidence', 'event_id', EvidenceEvent, exclude=('assessment',)),
        Collection('alertas', 'alerts', 'id', EmergencyAlert),
        Collection('eventos_voz', 'voice_events', 'id', VoiceEvent, exclude=('assessment', 'expires_at'),
                   keep=_voice_event_worth_keeping),
        Collection('fotogramas', 'event_frames', 'frame_id', EventFrame),
        Collection('personas_evento', 'person_candidates', 'candidate_id', DetectedPersonCandidate),
        Collection('perfiles', 'search_profiles', 'profile_id', SearchProfile, keep=lambda p: bool(p.case_id)),
        Collection('candidatos', 'candidate_matches', 'candidate_match_id', CandidateMatch,
                   nested_values={'signals': MatchSignal}),
        Collection('reapariciones', 'track_sightings', 'sighting_id', TrackSighting),
        Collection('solicitudes_eliminacion', 'deletion_requests', 'request_id', DeletionRequest),
        Collection('importaciones', 'imports', 'id', AlertImportRecord,
                   exclude=('camera_matches', 'reference_profile')),
        Collection('usuarios', 'users', 'id', User),
    ]


def _log_key(entry):
    row = (entry.timestamp, entry.user, entry.kind, entry.description, entry.case_id, entry.camera_id,
           entry.result, entry.device)
    return hashlib.sha1('|'.join(str(v) for v in row).encode('utf-8')).hexdigest(), row


# ------------------------------------------------------------------------- servicio
class LocalDatabase:
    def __init__(self, path=None):
        self.path = Path(path or config.LOCAL_DB_PATH)
        self.status = 'SIN_INICIAR'  # SIN_INICIAR · LISTA · ERROR
        self.error = None
        self.last_save = None
        self.loaded = False
        self._saved = {}  # (colección, clave) -> huella del contenido guardado
        self._order = {}  # colección -> tupla de claves en el orden guardado
        self._log_keys = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA synchronous=NORMAL')
        return connection

    @contextmanager
    def session(self):
        """Conexión que confirma al terminar, deshace si algo falla y siempre se cierra."""
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    # --------------------------------------------------------------- carga
    def load(self):
        """Lo guardado vuelve a la aplicación. La base manda sobre los datos de demostración."""
        with self._lock, self.session() as connection:
            connection.executescript(SCHEMA)
            counts = {}
            for collection in collections():
                rows = connection.execute('SELECT clave, datos, huella FROM documentos WHERE coleccion = ? '
                                          'ORDER BY posicion', (collection.name,)).fetchall()
                counts[collection.name] = len(rows)
                if not rows:
                    continue
                current = getattr(store, collection.attribute)
                by_key = {getattr(item, collection.key): item for item in current}
                loaded, keys = [], set()
                for key, data, digest in rows:
                    try:
                        item = collection.decode(data)
                    except Exception as error:  # un documento dañado no impide cargar los demás
                        logger.warning('Base local: no se pudo leer %s/%s: %s', collection.name, key, error)
                        continue
                    existing = by_key.get(key)
                    if existing is not None:  # expediente de demostración ya en memoria: se actualiza
                        existing.__dict__.update(item.__dict__)
                        item = existing
                    loaded.append(item)
                    keys.add(key)
                    self._saved[(collection.name, key)] = digest
                # Lo que la base no conoce (p. ej. una semilla nueva) se conserva al final.
                loaded += [item for item in current if getattr(item, collection.key) not in keys]
                current[:] = loaded
                self._order[collection.name] = tuple(getattr(i, collection.key) for i in collection.items())
            self._load_settings(connection)
            self._load_logs(connection)
        self.loaded, self.status, self.error = True, 'LISTA', None
        total = sum(counts.values())
        logger.info('Base local %s: %d documento(s) cargados', self.path, total)
        return counts

    def _load_settings(self, connection):
        row = connection.execute("SELECT datos FROM documentos WHERE coleccion = 'configuracion' AND "
                                 "clave = 'preferencias'").fetchone()
        if row:
            data = json.loads(row[0])
            for section, values in (data.get('settings') or {}).items():
                store.settings.setdefault(section, {}).update(values)
            if data.get('phrases'):
                store.phrases[:] = data['phrases']

    def _load_logs(self, connection):
        from models.audit_log import AuditLog
        local = {_log_key(entry)[0] for entry in store.logs}
        rows = connection.execute('SELECT clave_unica, fecha_hora, usuario, tipo, descripcion, caso_id, camara_id, '
                                  'resultado, dispositivo FROM bitacora ORDER BY fecha_hora DESC LIMIT ?',
                                  (config.LOCAL_DB_MAX_LOGS,)).fetchall()
        added = []
        for key, *row in rows:
            self._log_keys.add(key)
            if key not in local:
                added.append(AuditLog(*row))
        if added:
            store.logs.extend(added)
            store.logs.sort(key=lambda entry: entry.timestamp, reverse=True)

    # --------------------------------------------------------------- guardado
    def save(self):
        """Guarda sólo lo que cambió desde la última vez; reordena sin reescribir contenido."""
        if not self.loaded:
            return 0
        written = 0
        with self._lock, self.session() as connection:
            for collection in collections():
                items = collection.items()
                keys = []
                for item in items:
                    key = str(getattr(item, collection.key))
                    keys.append(key)
                    data = collection.encode(item)
                    digest = hashlib.sha1(data.encode('utf-8')).hexdigest()
                    if self._saved.get((collection.name, key)) == digest:
                        continue
                    connection.execute(
                        'INSERT INTO documentos (coleccion, clave, datos, huella, posicion, actualizado) '
                        "VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime')) "
                        'ON CONFLICT (coleccion, clave) DO UPDATE SET datos = excluded.datos, '
                        'huella = excluded.huella, actualizado = excluded.actualizado',
                        (collection.name, key, data, digest, len(keys) - 1))
                    self._saved[(collection.name, key)] = digest
                    written += 1
                order = tuple(keys)
                if order != self._order.get(collection.name):
                    connection.executemany('UPDATE documentos SET posicion = ? WHERE coleccion = ? AND clave = ?',
                                           [(index, collection.name, key) for index, key in enumerate(keys)])
                    gone = set(self._order.get(collection.name, ())) - set(keys)
                    for key in gone:  # lo que la aplicación descartó (importación cancelada, voz caducada)
                        connection.execute('DELETE FROM documentos WHERE coleccion = ? AND clave = ?',
                                           (collection.name, key))
                        self._saved.pop((collection.name, key), None)
                    self._order[collection.name] = order
            written += self._save_settings(connection)
            written += self._save_logs(connection)
        self.last_save, self.status, self.error = store.now(), 'LISTA', None
        return written

    def _save_settings(self, connection):
        data = json.dumps({'settings': store.settings, 'phrases': store.phrases}, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha1(data.encode('utf-8')).hexdigest()
        if self._saved.get(('configuracion', 'preferencias')) == digest:
            return 0
        connection.execute("INSERT INTO documentos (coleccion, clave, datos, huella) VALUES ('configuracion', "
                           "'preferencias', ?, ?) ON CONFLICT (coleccion, clave) DO UPDATE SET datos = excluded.datos, "
                           'huella = excluded.huella', (data, digest))
        self._saved[('configuracion', 'preferencias')] = digest
        return 1

    def _save_logs(self, connection):
        new = []
        for entry in list(store.logs):
            key, row = _log_key(entry)
            if key not in self._log_keys:
                new.append((key, *row))
                self._log_keys.add(key)
        if new:
            connection.executemany('INSERT OR IGNORE INTO bitacora (clave_unica, fecha_hora, usuario, tipo, '
                                   'descripcion, caso_id, camara_id, resultado, dispositivo) '
                                   'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', new)
        return len(new)

    # --------------------------------------------------------------- ciclo de vida
    def start(self):
        """Carga lo guardado y guarda los cambios cada LOCAL_DB_SAVE_SECONDS en segundo plano."""
        if self._thread and self._thread.is_alive():
            return
        try:
            self.load()
        except Exception as error:
            self.status, self.error = 'ERROR', str(error)
            logger.warning('Base local no disponible (%s): NEXO sigue en memoria.', error)
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='local-db', daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.wait(config.LOCAL_DB_SAVE_SECONDS):
            try:
                self.save()
            except Exception as error:  # el siguiente ciclo lo reintenta
                if self.error != str(error):
                    logger.warning('Base local: %s', error)
                self.status, self.error = 'ERROR', str(error)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        try:
            self.save()  # lo último que cambió antes de cerrar
        except Exception as error:
            logger.warning('Base local: no se pudo guardar al cerrar: %s', error)

    def summary(self):
        """Cuántos documentos hay por colección, para diagnóstico."""
        if not self.path.exists():
            return {}
        with self.session() as connection:
            rows = connection.execute('SELECT coleccion, COUNT(*) FROM documentos GROUP BY coleccion').fetchall()
            logs = connection.execute('SELECT COUNT(*) FROM bitacora').fetchone()[0]
        return {**dict(rows), 'bitacora': logs}


database = LocalDatabase()
