from dataclasses import dataclass


@dataclass
class AcousticFeatures:
    available: bool = False
    rms_energy: float | None = None
    relative_energy_change: float | None = None
    energy_variation: float | None = None
    pitch_mean: float | None = None
    pitch_variation: float | None = None
    speech_rate: float | None = None
    abrupt_change: bool = False
    reason: str = 'Sin audio; análisis únicamente semántico.'
