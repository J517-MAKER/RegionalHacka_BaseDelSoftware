from dataclasses import dataclass, field


@dataclass
class Camera:
    """Una cámara de la red. Se considera activa por sí misma: el resto del sistema no
    distingue si detrás hay una webcam, un archivo de video o una fuente simulada."""
    id: str
    name: str
    location: str
    zone: str
    status: str
    x: float
    y: float
    audio: bool = False
    last_seen: str = '2026-09-23 10:28:04'
    lat: float | None = None  # posición real en el mapa de México
    lng: float | None = None
    # Fuente del stream: 'webcam', 'file', 'rtsp' o 'simulated'. El consumidor usa el adapter.
    stream_source: str = 'simulated'
    stream_status: str = 'CAMERA_STREAM_ACTIVE'
    # Topología: cámaras contiguas, para evaluar coherencia de trayectoria.
    nearby_camera_ids: list = field(default_factory=list)

    @property
    def audio_available(self):
        return self.audio

    @property
    def last_seen_at(self):
        return self.last_seen
