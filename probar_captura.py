import numpy as np
from services.db_service import guardar_captura_rostro

# 1. Simular un vector de 512 números (generado por InsightFace o FaceNet)
vector_rostro = np.random.rand(512).astype(np.float32).tolist()

# 2. Guardar la captura de alerta
id_captura = guardar_captura_rostro(
    codigo_camara='CAM-CENTRO-01',
    embedding=vector_rostro,
    ruta_foto='assets/capturas/evento_grito_01.jpg',
    tipo_evento='ALERTA_AUDIO_SOSTENER'
)

print(f"✅ Captura registrada con éxito. ID en PostgreSQL: {id_captura}")