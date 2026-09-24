"""Circular audio buffer. Only the last seconds of sound exist, and only in memory."""
import threading
import config


class AudioRing:
    def __init__(self, seconds=None, sample_rate=None):
        import numpy as np
        self.rate = sample_rate or config.AUDIO_SAMPLE_RATE
        self.capacity = max(1, int((seconds or config.AUDIO_RING_SECONDS) * self.rate))
        self.buffer = np.zeros(self.capacity, dtype='float32')
        self.written = 0
        self.lock = threading.Lock()

    def write(self, chunk):
        import numpy as np
        data = np.asarray(chunk, dtype='float32').reshape(-1)
        if data.size > self.capacity:
            data = data[-self.capacity:]
        with self.lock:
            position = self.written % self.capacity
            first = min(data.size, self.capacity - position)
            self.buffer[position:position + first] = data[:first]
            self.buffer[:data.size - first] = data[first:]
            self.written += data.size
        return self.written

    def oldest(self):
        """First absolute sample still available; anything older was discarded."""
        return max(0, self.written - self.capacity)

    def read(self, start, end):
        """Absolute sample range, clipped to what the buffer still holds."""
        import numpy as np
        with self.lock:
            start = max(int(start), self.oldest(), 0)
            end = min(int(end), self.written)
            if end <= start:
                return np.zeros(0, dtype='float32')
            position = start % self.capacity
            first = min(end - start, self.capacity - position)
            return np.concatenate([self.buffer[position:position + first],
                                   self.buffer[:end - start - first]])

    def clear(self):
        with self.lock:
            self.buffer[:] = 0
            self.written = 0
