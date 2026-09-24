"""Observable energy only: no emotion or danger inferred from loudness."""
import config
from models.acoustic_features import AcousticFeatures


def analyze_audio(audio, previous_energies=(), sample_rate=None):
    if audio is None:
        return AcousticFeatures()
    try:
        import numpy as np
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        rate = sample_rate or config.AUDIO_SAMPLE_RATE
        if rate <= 0 or samples.size < rate // 10 or not np.isfinite(samples).all():
            return AcousticFeatures(reason='Audio insuficiente o inválido para medir energía.')
        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
        frame_size = max(1, rate // 4)
        frames = [float(np.sqrt(np.mean(samples[i:i+frame_size].astype(np.float64) ** 2)))
                  for i in range(0, len(samples), frame_size)]
        baseline = [v for v in previous_energies if v is not None and np.isfinite(v) and v > .0001]
        ratio = rms / float(np.median(baseline)) if baseline else None
        return AcousticFeatures(available=True, rms_energy=rms, relative_energy_change=ratio,
                                energy_variation=float(np.std(frames)),
                                abrupt_change=ratio is not None and ratio >= config.ACOUSTIC_CHANGE_RATIO,
                                reason='Comparación con energía reciente.' if baseline else 'Sin referencia previa suficiente; no se infiere cambio abrupto.')
    except Exception:
        return AcousticFeatures(reason='Análisis acústico no disponible; se mantiene la semántica.')


def audio_windows(audio, sample_rate=None):
    """Yield bounded (start_seconds, end_seconds, samples) views; no disk writes."""
    rate = sample_rate or config.AUDIO_SAMPLE_RATE
    size = int(config.AUDIO_WINDOW_SECONDS * rate)
    step = int((config.AUDIO_WINDOW_SECONDS - config.AUDIO_OVERLAP_SECONDS) * rate)
    if size <= 0 or step <= 0:
        raise ValueError('La ventana debe ser mayor que su solapamiento.')
    for start in range(0, len(audio), step):
        end = min(start + size, len(audio))
        yield start / rate, end / rate, audio[start:end]
        if end == len(audio):
            break
