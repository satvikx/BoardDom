"""In-memory failure counters for brute-force protection.

Single-process only: state lives in this process and resets on restart. Swap this
class for a shared store (e.g. Redis) when running more than one API process.
Keys must not be client IPs: requests arrive through the Next.js proxy, so every
client appears as 127.0.0.1.
"""

import math
import threading
import time
from collections.abc import Callable


class FailureLimiter:
    """Lock a key for `lockout_seconds` after `max_failures` failures within `window_seconds`."""

    def __init__(
        self,
        max_failures: int,
        window_seconds: float,
        lockout_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self.clock = clock
        self.max_keys = max_keys
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        """Seconds until `key` may try again; 0 when it is not locked."""
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return 0
            remaining = until - self.clock()
            if remaining <= 0:
                del self._locked_until[key]
                return 0
            return math.ceil(remaining)

    def record_failure(self, key: str) -> int:
        """Record a failure. Returns seconds locked (0 if this failure did not lock)."""
        with self._lock:
            now = self.clock()
            if len(self._failures) >= self.max_keys:
                self._prune(now)
            recent = [t for t in self._failures.get(key, []) if now - t < self.window_seconds]
            recent.append(now)
            if len(recent) >= self.max_failures:
                self._failures.pop(key, None)
                self._locked_until[key] = now + self.lockout_seconds
                return math.ceil(self.lockout_seconds)
            self._failures[key] = recent
            return 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def _prune(self, now: float) -> None:
        self._failures = {
            k: v for k, v in self._failures.items() if v and now - v[-1] < self.window_seconds
        }
        self._locked_until = {k: u for k, u in self._locked_until.items() if u > now}
        # Still full of active keys: drop the oldest to bound memory.
        while len(self._failures) >= self.max_keys:
            self._failures.pop(next(iter(self._failures)))


def minutes_text(seconds: int) -> str:
    minutes = max(1, math.ceil(seconds / 60))
    return f"{minutes} minute{'s' if minutes != 1 else ''}"
