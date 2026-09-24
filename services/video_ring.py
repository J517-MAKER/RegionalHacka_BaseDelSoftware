"""Anillo de video en memoria: los últimos segundos de una cámara, comprimidos en JPEG.

Lo que ningún evento reclama se sobrescribe. Cuando se escucha una posible solicitud de
auxilio, el tramo alrededor de ese instante se copia a la evidencia; el resto nunca llega
al disco.
"""
import threading
import time
from datetime import datetime
import config


class VideoRing:
    """Fotogramas recientes con el instante en que la cámara los entregó.

    Se guardan comprimidos: en crudo, medio minuto de una cámara a 640x480 ocuparía cientos
    de megabytes, y aquí sólo hacen falta para reconstruir los segundos alrededor de un evento.
    """

    def __init__(self, seconds=None, fps=None, quality=None):
        self.seconds = seconds or config.VIDEO_RING_SECONDS
        self.fps = fps or config.VIDEO_RING_FPS
        self.quality = quality or config.VIDEO_RING_JPEG_QUALITY
        self.capacity = max(1, int(self.seconds * self.fps))
        self.frames = []  # [(monotónico, fecha y hora, jpeg)]
        self.lock = threading.Lock()
        self._last_write = float('-inf')

    @staticmethod
    def encode(frame, quality=None):
        import cv2
        ok, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY,
                                                  quality or config.VIDEO_RING_JPEG_QUALITY])
        return buffer.tobytes() if ok else None

    @staticmethod
    def decode(payload):
        import cv2
        import numpy as np
        return cv2.imdecode(np.frombuffer(payload, dtype='uint8'), cv2.IMREAD_COLOR)

    def due(self, now=None):
        """True cuando toca guardar otro cuadro: la cámara entrega más de los que hacen falta."""
        return (time.monotonic() if now is None else now) - self._last_write >= 1 / self.fps

    def write(self, frame, when=None, at=None):
        payload = frame if isinstance(frame, (bytes, bytearray)) else self.encode(frame, self.quality)
        if payload is None:
            return
        now = time.monotonic() if at is None else at
        with self.lock:
            self._last_write = now
            self.frames.append((now, when or datetime.now(), payload))
            # Se descarta por antigüedad y por tamaño: el anillo nunca crece sin límite.
            horizon = now - self.seconds
            self.frames = [f for f in self.frames if f[0] >= horizon][-self.capacity:]

    def window(self, pre_seconds=None, post_seconds=None, reference=None):
        """Fotogramas alrededor de un instante. Devuelve lo que el anillo todavía conserva."""
        pre = config.VIDEO_PRE_EVENT_SECONDS if pre_seconds is None else pre_seconds
        post = config.VIDEO_POST_EVENT_SECONDS if post_seconds is None else post_seconds
        mark = reference if reference is not None else time.monotonic()
        with self.lock:
            return [f for f in self.frames if mark - pre <= f[0] <= mark + post]

    def latest(self):
        with self.lock:
            return self.frames[-1] if self.frames else None

    def span(self):
        """Segundos de video que el anillo conserva ahora mismo."""
        with self.lock:
            return self.frames[-1][0] - self.frames[0][0] if len(self.frames) > 1 else 0.0

    def clear(self):
        with self.lock:
            self.frames.clear()
            self._last_write = float('-inf')
