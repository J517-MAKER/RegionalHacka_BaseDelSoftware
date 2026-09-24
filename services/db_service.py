import psycopg
from pgvector.psycopg import register_vector
import os

# Configuración de conexión con PostgreSQL en Docker
DB_CONFIG = os.getenv(
    'DATABASE_URL',
    'dbname=db_desaparecidos user=admin password=mi_password_seguro host=localhost port=5432'
)

def get_db_connection():
    """Establece la conexión con PostgreSQL y habilita el tipo VECTOR."""
    conn = psycopg.connect(DB_CONFIG)
    register_vector(conn)
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