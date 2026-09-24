"""Reaparición de una persona vista durante un evento de auxilio en otra cámara del equipo.

Sirve para reconstruir por dónde se movió después del evento («caminó de la cámara A a la
B»). No identifica a nadie: sólo dice que un rostro parecido al de la persona del evento
apareció en tal cámara a tal hora, y queda para revisión humana.
"""
from dataclasses import dataclass


@dataclass
class TrackSighting:
    sighting_id: str
    event_id: str
    candidate_id: str  # DetectedPersonCandidate del evento
    track_id: str  # PERSON-TRACK-A, B…
    camera_id: str
    timestamp: str
    # Parecido con el rostro del evento. Interno: ordena y decide el nivel, no se muestra solo.
    similarity: float = 0.0
    level: str = 'BAJA'
    capture: str = ''  # recorte del rostro (data URL), para que una persona lo compare
    status: str = 'Pendiente de validación'
