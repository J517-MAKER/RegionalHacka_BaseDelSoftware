import numpy as np
from services.facial_service import registrar_rostro_detectado, get_matches

print("--- 1. Guardando captura de alerta con vector simulado ---")
# Simula un vector de 512 dimensiones generado por el modelo de rostros
vector_ficticio = np.random.rand(512).astype(np.float32).tolist()

id_captura = registrar_rostro_detectado(
    codigo_camara="CAM-CENTRO-01",
    embedding_rostro=vector_ficticio,
    ruta_imagen="assets/capturas/prueba.jpg",
    tipo_evento="GRITO_AUXILIO"
)
print(f"Éxito: Captura guardada en Postgres con ID: {id_captura}")

print("\n--- 2. Probando búsqueda por similitud vectorial ---")
# Buscamos usando el mismo vector para asegurar un 100% de similitud
coincidencias = get_matches(vector_busqueda=vector_ficticio)

print(f"Coincidencias encontradas: {len(coincidencias)}")
for c in coincidencias:
    print(f" -> Cámara: {c[1]} | Fecha: {c[2]} | Similitud: {c[4]*100:.2f}%")