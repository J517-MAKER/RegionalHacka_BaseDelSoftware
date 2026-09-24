import psycopg
from pgvector.psycopg import register_vector
import numpy as np

# Conexión a la BD
conn = psycopg.connect("dbname=db_desaparecidos user=admin password=mi_password_seguro host=localhost port=5432")
register_vector(conn)

# Generar o definir el vector de la foto del boletín de búsqueda (512 dimensiones)
# En un entorno real, este vector se extrae de la foto del reporte que sube la autoridad
vector_boletin = np.random.rand(512).astype(np.float32).tolist()

with conn.cursor() as cur:
    cur.execute("""
        INSERT INTO expedientes_desaparecidos (
            folio_reporte,
            nombre_completo,
            fecha_desaparicion,
            descripcion_fisica,
            metadata_rasgos,
            embedding_referencia
        ) VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
    """, (
        'REP-2026-001',
        'Juan Pérez López',
        '2026-09-20',
        'Estatura 1.75m, tez morena clara, vestía camisa azul y pantalón negro.',
        psycopg.types.json.Jsonb({"tez": "morena clara", "vestimenta": "camisa azul"}),
        vector_boletin
    ))
    expediente_id = cur.fetchone()[0]
    conn.commit()
    print(f"✅ Expediente creado con exito. ID: {expediente_id}")

conn.close()