"""Acceso a PostgreSQL (docker-compose.yml): opcional y compartido por el equipo.

El controlador se importa sólo al conectarse: si psycopg o pgvector no están instalados en
un equipo, NEXO arranca igual y trabaja con su base local (services/local_db.py).
"""
import os
import re
import socket

# Configuración de conexión con PostgreSQL en Docker
DB_CONFIG = os.getenv(
    'DATABASE_URL',
    'dbname=db_desaparecidos user=admin password=mi_password_seguro host=localhost port=5432'
)


def _driver():
    try:
        import psycopg
        from pgvector.psycopg import register_vector
    except ImportError as error:
        raise ConnectionError('Falta el controlador de PostgreSQL (psycopg/pgvector). '
                              'Ejecuta: python -m pip install -r requirements.txt') from error
    return psycopg, register_vector


def driver_installed():
    try:
        _driver()
        return True
    except ConnectionError:
        return False


def _host_port():
    """Host y puerto de DB_CONFIG, tanto en formato 'host=... port=...' como postgresql://."""
    if '://' in DB_CONFIG:
        from urllib.parse import urlparse
        url = urlparse(DB_CONFIG)
        return url.hostname or 'localhost', url.port or 5432
    host = re.search(r'host=(\S+)', DB_CONFIG)
    port = re.search(r'port=(\d+)', DB_CONFIG)
    return (host[1] if host else 'localhost'), (int(port[1]) if port else 5432)


def database_available(timeout=.5):
    """Prueba rápida del puerto: sin ella psycopg espera mucho cuando el contenedor está apagado."""
    try:
        socket.create_connection(_host_port(), timeout=timeout).close()
        return True
    except OSError:
        return False


def get_db_connection():
    """Establece la conexión con PostgreSQL y habilita el tipo VECTOR."""
    psycopg, register_vector = _driver()
    conn = psycopg.connect(DB_CONFIG, connect_timeout=5)
    try:
        register_vector(conn)
    except psycopg.ProgrammingError:
        pass  # la extensión vector aún no existe: la crea db_bootstrap.initialize_database()
    return conn


def guardar_captura_rostro(codigo_camara: str, embedding: list, ruta_foto: str, tipo_evento: str = 'ALERTA_AUDIO'):
    """Guarda en la BD la captura tomada por una cámara junto a su vector facial (512d)."""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM camaras WHERE codigo_camara = %s;", (codigo_camara,))
            cam_res = cur.fetchone()
            if not cam_res:
                print(f"La cámara {codigo_camara} no existe en la BD.")
                conn.close()
                return None

            id_camara = cam_res[0]

            cur.execute("""
                INSERT INTO capturas_alerta (id_camara, embedding_rostro, ruta_imagen, tipo_evento)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
            """, (id_camara, embedding, ruta_foto, tipo_evento))

            captura_id = cur.fetchone()[0]
            conn.commit()
            conn.close()
            return captura_id
    except Exception as e:
        print(f"Error al guardar la captura en la BD: {e}")
        return None


def buscar_coincidencias_rostro(embedding_busqueda, umbral=0.70, limite=10):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    ca.id,
                    c.codigo_camara,
                    ca.fecha_hora,
                    ca.ruta_imagen,
                    1 - (ca.embedding_rostro <=> %s::vector) AS similitud
                FROM capturas_alerta ca
                JOIN camaras c ON ca.id_camara = c.id
                WHERE 1 - (ca.embedding_rostro <=> %s::vector) >= %s
                ORDER BY similitud DESC
                LIMIT %s;
            """, (embedding_busqueda, embedding_busqueda, umbral, limite))
            return cur.fetchall()


def listar_capturas(limite=500):
    """Capturas con huella registradas por cualquier instancia del equipo, más recientes primero.

    Las que vienen de un evento de esta misma instancia se omiten: ya están en memoria con su
    evidencia completa y aparecerían dos veces.
    """
    from services import store
    local_events = {event.event_id for event in store.evidence}
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ca.id, c.codigo_camara, ca.fecha_hora, COALESCE(ca.imagen_base64, ca.ruta_imagen),
                       ca.tipo_evento, ca.embedding_rostro
                FROM capturas_alerta ca
                JOIN camaras c ON ca.id_camara = c.id
                ORDER BY ca.fecha_hora DESC
                LIMIT %s;
            """, (limite,))
            rows = cur.fetchall()
    captures = []
    for identifier, camera, moment, image, kind, embedding in rows:
        if kind and any(event_id in kind for event_id in local_events):
            continue
        when = moment.astimezone().strftime('%Y-%m-%d %H:%M:%S') if hasattr(moment, 'astimezone') else str(moment)
        captures.append({'id': identifier, 'codigo_camara': camera, 'fecha_hora': when,
                         'ruta_imagen': image if image and (image.startswith('data:') or image.startswith('/')) else '',
                         'tipo_evento': kind or '', 'embedding': [float(v) for v in embedding]})
    return captures


def compartir_capturas_evento(event_id):
    """Sube a la base compartida los rostros de un evento, para que otras instancias del equipo
    puedan compararlos contra sus fichas. Sin base conectada no hace nada."""
    from services import store
    from services.db_sync import database
    if database.status != 'SINCRONIZADA':
        return 0
    import base64
    import config
    shared = 0
    for candidate in [c for c in store.person_candidates if c.event_id == event_id and c.face_embedding]:
        image = ''
        path = config.BASE_DIR / candidate.face_image_path if candidate.face_image_path else None
        if path is not None and path.exists():
            image = 'data:image/jpeg;base64,' + base64.b64encode(path.read_bytes()).decode()
        if guardar_captura_rostro(candidate.camera_id, candidate.face_embedding, image,
                                  f'EVENTO_AUXILIO:{event_id}:{candidate.person_track_id}'):
            shared += 1
    return shared
