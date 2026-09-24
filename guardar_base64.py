import base64
import cv2
import numpy as np
import psycopg
from pgvector.psycopg import register_vector

def guardar_captura_en_bd(codigo_camara, vector_rostro, frame_cv2, tipo_evento):
    # 1. Convertir la imagen de OpenCV (frame) a formato JPG en memoria
    _, buffer = cv2.imencode('.jpg', frame_cv2)
    
    # 2. Convertir el buffer a texto Base64
    imagen_base64 = base64.b64encode(buffer).decode('utf-8')
    
    # 3. Conectar a PostgreSQL
    conn = psycopg.connect("dbname=db_desaparecidos user=admin password=mi_password_seguro host=localhost port=5432")
    register_vector(conn)
    
    with conn.cursor() as cur:
        # Obtener ID de la cámara
        cur.execute("SELECT id FROM camaras WHERE codigo_camara = %s;", (codigo_camara,))
        res = cur.fetchone()
        id_camara = res[0] if res else None

        # Insertar el vector Y la imagen en la misma tabla
        cur.execute("""
            INSERT INTO capturas_alerta (id_camara, embedding_rostro, tipo_evento, imagen_base64)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
        """, (id_camara, vector_rostro, tipo_evento, imagen_base64))
        
        captura_id = cur.fetchone()[0]
        conn.commit()
        print(f"✅ Captura guardada directamente en BD (Sin archivos en disco). ID: {captura_id}")
        
    conn.close()

# --- PRUEBA DEL SCRIPT ---
if __name__ == "__main__":
    # Crear una imagen negra de prueba en OpenCV
    frame_prueba = np.zeros((300, 300, 3), dtype=np.uint8)
    vector_simulado = np.random.rand(512).astype(np.float32).tolist()
    
    guardar_captura_en_bd('CAM-CENTRO-01', vector_simulado, frame_prueba, 'PRUEBA_BASE64')
    