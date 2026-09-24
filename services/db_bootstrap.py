"""Inicialización opcional y segura del esquema PostgreSQL."""
import logging

from services.db_service import get_db_connection

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS personas (
    id BIGSERIAL PRIMARY KEY,
    nombre_completo TEXT NOT NULL,
    edad INTEGER,
    sexo TEXT,
    nacionalidad TEXT,
    descripcion_fisica TEXT,
    senas_particulares TEXT,
    fecha_desaparicion DATE,
    lugar_desaparicion TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fotografias_persona (
    id BIGSERIAL PRIMARY KEY,
    persona_id BIGINT NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
    ruta_imagen TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'referencia',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS camaras (
    id BIGSERIAL PRIMARY KEY,
    codigo_camara TEXT UNIQUE NOT NULL,
    nombre TEXT NOT NULL,
    ubicacion TEXT,
    latitud DOUBLE PRECISION,
    longitud DOUBLE PRECISION,
    activa BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS embeddings_persona (
    id BIGSERIAL PRIMARY KEY,
    persona_id BIGINT NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
    embedding VECTOR(512) NOT NULL,
    modelo TEXT NOT NULL,
    version_modelo TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS capturas_alerta (
    id BIGSERIAL PRIMARY KEY,
    persona_id BIGINT REFERENCES personas(id) ON DELETE SET NULL,
    id_camara BIGINT NOT NULL REFERENCES camaras(id),
    embedding_rostro VECTOR(512) NOT NULL,
    ruta_imagen TEXT,
    tipo_evento TEXT NOT NULL DEFAULT 'DETECCION',
    fecha_hora TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS historial_busquedas (
    id BIGSERIAL PRIMARY KEY,
    persona_id BIGINT REFERENCES personas(id) ON DELETE SET NULL,
    usuario TEXT,
    consulta TEXT,
    resultado TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS embeddings_persona_vector_idx ON embeddings_persona USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS capturas_alerta_vector_idx ON capturas_alerta USING hnsw (embedding_rostro vector_cosine_ops);
CREATE INDEX IF NOT EXISTS capturas_alerta_fecha_idx ON capturas_alerta (fecha_hora DESC);

INSERT INTO camaras (codigo_camara, nombre, ubicacion)
VALUES ('CAM-008', 'Cámara principal', 'Pasillo B')
ON CONFLICT (codigo_camara) DO NOTHING;
"""


def initialize_database():
    """Crea el esquema al arrancar; no elimina ni reinicia datos existentes."""
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(SCHEMA_SQL)
    logger.info("Esquema PostgreSQL inicializado")
