import base64
import psycopg

# Conectarse a PostgreSQL en Docker
conn = psycopg.connect("dbname=db_desaparecidos user=admin password=mi_password_seguro host=localhost port=5432")

with conn.cursor() as cur:
    # Obtener la última captura guardada que tenga imagen Base64
    cur.execute("""
        SELECT id, tipo_evento, fecha_hora, imagen_base64 
        FROM capturas_alerta 
        WHERE imagen_base64 IS NOT NULL 
        ORDER BY fecha_hora DESC 
        LIMIT 1;
    """)
    resultado = cur.fetchone()

    if resultado:
        captura_id, tipo_evento, fecha, b64_text = resultado
        print(f"Descargando foto de la captura ID: {captura_id} ({tipo_evento})")
        
        # Decodificar el texto Base64 a bytes de imagen JPG
        img_bytes = base64.b64decode(b64_text)
        
        # Guardar temporalmente para visualizar
        nombre_archivo = f"foto_extraida_{captura_id}.jpg"
        with open(nombre_archivo, "wb") as f:
            f.write(img_bytes)
            
        print(f"✅ ¡Imagen guardada exitosamente como '{nombre_archivo}' en tu carpeta!")
    else:
        print("No se encontraron capturas con imágenes en la base de datos.")

conn.close()
