"""A bad cable: a link that damages bytes on their way back to the client.

Used to test the client, not the device: whatever the line does, the client must never hand out a
value the device did not send.
"""

from __future__ import annotations

import random
import time

from inverter_lab.links import Link


class NoisyLink:
    """Flips single bits in received data with probability ``bit_error_rate`` per bit."""

    def __init__(self, inner: Link, bit_error_rate: float, seed: int = 2026) -> None:
        self.inner = inner
        self.bit_error_rate = bit_error_rate
        self.random = random.Random(seed)
        self.flipped = 0

    def write(self, data: bytes) -> None:
        self.inner.write(data)

    def read(self, timeout: float) -> bytes:
        data = bytearray(self.inner.read(timeout))
        for index in range(len(data)):
            for bit in range(8):
                if self.random.random() < self.bit_error_rate:
                    data[index] ^= 1 << bit
                    self.flipped += 1
        return bytes(data)

    def reset_input(self) -> None:
        self.inner.reset_input()

    def close(self) -> None:
        self.inner.close()


class ScriptedLink:
    """A link whose answers are written in advance: each write is answered by the next scripted reply."""

    def __init__(self, replies: list[bytes]) -> None:
        self.replies = list(replies)
        self.sent: list[bytes] = []
        self._pending = b""

    def write(self, data: bytes) -> None:
        self.sent.append(data)
        self._pending = self.replies.pop(0) if self.replies else b""

    def read(self, timeout: float) -> bytes:
        data, self._pending = self._pending, b""
        if not data:
            time.sleep(min(timeout, 0.01))  # nothing on the line: do not spin
        return data

    def reset_input(self) -> None:
        self._pending = b""

    def close(self) -> None:
        pass
