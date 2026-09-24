from dataclasses import dataclass


@dataclass
class Camera:
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
