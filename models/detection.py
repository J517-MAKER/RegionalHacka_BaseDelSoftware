from dataclasses import dataclass


@dataclass
class Detection:
    id: str
    case_id: str
    camera_id: str
    timestamp: str
    similarity: int
    status: str = 'Pendiente de validación'
    quality: str = 'Adecuada'
    capture: str = '/assets/demo/capture.svg'
    # Huella del rostro capturado: permite comparar esta captura contra fichas registradas
    # después. Vacía en las detecciones de demostración, que no tienen un rostro real.
    embedding: list | None = None
    # Rasgos estimados de la imagen, sólo orientativos: nunca descartan a nadie.
    estimated_age: int | None = None
    clothing_color: str | None = None


@dataclass
class TrackingEvent:
    detection: Detection
    order: int
