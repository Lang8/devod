"""Shared polite HTTP client: fixed User-Agent, per-host throttle, timeout, bounded retries.

The transport is injectable (``transport(url, headers, timeout) -> (status, body)``) so
tests never touch the network.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

USER_AGENT = "DeutschTrainerIngest/1.0 (+https://github.com/Lang8/devod)"
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3

Transport = Callable[[str, dict, float], "tuple[int, str]"]


class FetchError(RuntimeError):
    """A fetch failed after all attempts."""


def urllib_transport(url: str, headers: dict, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


class HttpClient:
    def __init__(self, transport: Transport | None = None, rate: float = 1.0,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 timeout: float = TIMEOUT_SECONDS, attempts: int = MAX_ATTEMPTS):
        if rate <= 0:
            raise ValueError("rate must be > 0 requests per second")
        self.transport = transport or urllib_transport
        self.min_interval = 1.0 / rate
        self._sleep, self._clock = sleep, clock
        self.timeout, self.attempts = timeout, attempts
        self._last: dict[str, float] = {}

    def _throttle(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            wait = self.min_interval - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last[host] = self._clock()

    def get(self, url: str, params: dict | None = None) -> str:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        host = urllib.parse.urlparse(url).hostname or ""
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        last_error = "unknown error"
        for _ in range(self.attempts):
            self._throttle(host)
            try:
                status, body = self.transport(url, headers, self.timeout)
            except Exception as exc:  # timeouts, connection errors
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            if status == 200:
                return body
            last_error = f"HTTP {status}"
            if status != 429 and status < 500:
                break  # client errors are not retried
        raise FetchError(f"GET {url} failed after {self.attempts} attempts: {last_error}")
