# services/db_bootstrap.py
"""Esquema PostgreSQL de NEXO. Es idempotente: se puede ejecutar en cada arranque.

Las sentencias ALTER ... ADD COLUMN IF NOT EXISTS actualizan bases creadas con una
versión anterior de este esquema sin perder datos.
"""
import logging
from services.db_service import get_db_connection

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

-- Personas desaparecidas: un renglón por expediente (folio BUS-AAAA-NNNN de la aplicación).
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
ALTER TABLE personas ADD COLUMN IF NOT EXISTS folio TEXT;
ALTER TABLE personas ADD COLUMN IF NOT EXISTS estatura TEXT;
ALTER TABLE personas ADD COLUMN IF NOT EXISTS complexion TEXT;
ALTER TABLE personas ADD COLUMN IF NOT EXISTS tez TEXT;
ALTER TABLE personas ADD COLUMN IF NOT EXISTS cabello TEXT;
ALTER TABLE personas ADD COLUMN IF NOT EXISTS ojos TEXT;
ALTER TABLE personas ADD COLUMN IF NOT EXISTS vestimenta TEXT;
ALTER TABLE personas ADD COLUMN IF NOT EXISTS hora_desaparicion TEXT;
ALTER TABLE personas ADD COLUMN IF NOT EXISTS zona TEXT;
ALTER TABLE personas ADD COLUMN IF NOT EXISTS estado TEXT NOT NULL DEFAULT 'En búsqueda';
ALTER TABLE personas ADD COLUMN IF NOT EXISTS responsable TEXT;
ALTER TABLE personas ADD COLUMN IF NOT EXISTS fecha_reporte TIMESTAMP;
ALTER TABLE personas ADD COLUMN IF NOT EXISTS estado_referencia TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS personas_folio_idx ON personas (folio);
CREATE INDEX IF NOT EXISTS personas_estado_idx ON personas (estado);

-- Fotografías de referencia. ruta_imagen guarda la ruta (/assets/...) o la imagen
-- completa como data URL (data:image/jpeg;base64,...), igual que la aplicación.
CREATE TABLE IF NOT EXISTS fotografias_persona (
    id BIGSERIAL PRIMARY KEY,
    persona_id BIGINT NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
    ruta_imagen TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'referencia',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE fotografias_persona ADD COLUMN IF NOT EXISTS orden INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS camaras (
    id BIGSERIAL PRIMARY KEY,
    codigo_camara TEXT UNIQUE NOT NULL,
    nombre TEXT NOT NULL,
    ubicacion TEXT,
    latitud DOUBLE PRECISION,
    longitud DOUBLE PRECISION,
    activa BOOLEAN NOT NULL DEFAULT TRUE
);
ALTER TABLE camaras ADD COLUMN IF NOT EXISTS zona TEXT;
ALTER TABLE camaras ADD COLUMN IF NOT EXISTS estado TEXT;
ALTER TABLE camaras ADD COLUMN IF NOT EXISTS ultima_comunicacion TEXT;

CREATE TABLE IF NOT EXISTS embeddings_persona (
    id BIGSERIAL PRIMARY KEY,
    persona_id BIGINT NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
    embedding VECTOR(512) NOT NULL,
    modelo TEXT NOT NULL,
    version_modelo TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Detecciones de posibles coincidencias (una por persona, cámara y ventana de tiempo)
-- con el estado de su revisión humana.
CREATE TABLE IF NOT EXISTS detecciones (
    id BIGSERIAL PRIMARY KEY,
    codigo TEXT UNIQUE NOT NULL,
    persona_id BIGINT REFERENCES personas(id) ON DELETE CASCADE,
    folio TEXT NOT NULL,
    id_camara BIGINT REFERENCES camaras(id),
    codigo_camara TEXT NOT NULL,
    fecha_hora TIMESTAMP,
    similitud INTEGER,
    calidad TEXT,
    estado TEXT,
    captura TEXT,
    coincidencia_codigo TEXT,
    revisado_por TEXT,
    revisado_en TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS detecciones_folio_idx ON detecciones (folio, fecha_hora DESC);

CREATE TABLE IF NOT EXISTS capturas_alerta (
    id BIGSERIAL PRIMARY KEY,
    persona_id BIGINT REFERENCES personas(id) ON DELETE SET NULL,
    id_camara BIGINT NOT NULL REFERENCES camaras(id),
    embedding_rostro VECTOR(512) NOT NULL,
    ruta_imagen TEXT,
    tipo_evento TEXT NOT NULL DEFAULT 'DETECCION',
    fecha_hora TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE capturas_alerta ADD COLUMN IF NOT EXISTS imagen_base64 TEXT;

CREATE TABLE IF NOT EXISTS historial_busquedas (
    id BIGSERIAL PRIMARY KEY,
    persona_id BIGINT REFERENCES personas(id) ON DELETE SET NULL,
    usuario TEXT,
    consulta TEXT,
    resultado TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS embeddings_persona_vector_idx
    ON embeddings_persona USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS capturas_alerta_vector_idx
    ON capturas_alerta USING hnsw (embedding_rostro vector_cosine_ops);

CREATE INDEX IF NOT EXISTS capturas_alerta_fecha_idx
    ON capturas_alerta (fecha_hora DESC);

-- Consulta lista para usar: personas que siguen desaparecidas, con su actividad.
DROP VIEW IF EXISTS v_personas_desaparecidas;
CREATE VIEW v_personas_desaparecidas AS
SELECT p.folio,
       p.nombre_completo,
       p.edad,
       p.sexo,
       p.fecha_desaparicion,
       p.hora_desaparicion,
       p.lugar_desaparicion,
       p.zona,
       p.estado,
       p.responsable,
       p.fecha_reporte,
       (SELECT COUNT(*) FROM fotografias_persona f WHERE f.persona_id = p.id) AS fotografias,
       (SELECT COUNT(*) FROM detecciones d WHERE d.persona_id = p.id) AS detecciones,
       (SELECT MAX(d.fecha_hora) FROM detecciones d WHERE d.persona_id = p.id) AS ultima_deteccion,
       (SELECT d.codigo_camara FROM detecciones d WHERE d.persona_id = p.id
         ORDER BY d.fecha_hora DESC NULLS LAST LIMIT 1) AS ultima_camara
FROM personas p
WHERE p.folio IS NOT NULL AND p.estado NOT IN ('Localizada', 'Cerrada')
ORDER BY p.fecha_reporte DESC NULLS LAST;

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


if __name__ == '__main__':
    initialize_database()
    print('Esquema de la base de datos creado o actualizado.')
