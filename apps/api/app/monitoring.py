"""Optional success heartbeats; monitoring failures never fail application work."""

from __future__ import annotations

import logging
import time
from urllib.request import Request, urlopen

logger = logging.getLogger("tuskometr.monitoring")


class Heartbeat:
    def __init__(self, url: str, name: str, interval: float = 60) -> None:
        self.url = url.strip()
        self.name = name
        self.interval = interval
        self.last_attempt: float | None = None

    def ping(self) -> None:
        if not self.url:
            return
        now = time.monotonic()
        if self.last_attempt is not None and now - self.last_attempt < self.interval:
            return
        # Throttle failed attempts too, and never queue retries of old successes.
        self.last_attempt = now
        try:
            request = Request(self.url, data=b"", method="POST")
            with urlopen(request, timeout=3) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError("Unexpected heartbeat response")
        except Exception:
            # Exception messages may contain the private ping URL.
            logger.warning("Healthchecks heartbeat failed (%s)", self.name)
