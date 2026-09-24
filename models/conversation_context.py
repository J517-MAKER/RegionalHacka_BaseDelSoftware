"""Ephemeral, per-console conversation memory. No raw audio is retained."""
from collections import deque
from dataclasses import dataclass
from time import monotonic
import config


@dataclass
class TranscriptSegment:
    timestamp: float
    text: str
    rms_energy: float | None = None


class ConversationContext:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.segments = deque(maxlen=config.CONTEXT_MAX_SEGMENTS)

    def prune(self, now=None):
        now = self.clock() if now is None else now
        while self.segments and self.segments[0].timestamp < now - config.CONTEXT_SECONDS:
            self.segments.popleft()

    def recent(self, now=None):
        self.prune(now)
        return list(self.segments)

    def add(self, text, rms_energy=None, timestamp=None):
        timestamp = self.clock() if timestamp is None else timestamp
        self.prune(timestamp)
        self.segments.append(TranscriptSegment(timestamp, text[:config.CONTEXT_MAX_TEXT], rms_energy))

    def clear(self):
        self.segments.clear()
