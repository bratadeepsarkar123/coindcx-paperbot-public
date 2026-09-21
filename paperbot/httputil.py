"""Polite HTTP GET with 429 backoff. Stdlib only."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger("paperbot.http")


class HttpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class PoliteHttp:
    def __init__(
        self,
        *,
        timeout_sec: float = 15.0,
        min_interval_sec: float = 0.25,
        max_retries: int = 5,
        user_agent: str = "bratadeep-coindcx-paperbot/0.1",
    ) -> None:
        self.timeout_sec = timeout_sec
        self.min_interval_sec = min_interval_sec
        self.max_retries = max_retries
        self.user_agent = user_agent
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last_request_at
        if gap < self.min_interval_sec:
            time.sleep(self.min_interval_sec - gap)

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        delay = 1.0
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            req = urllib.request.Request(
                url,
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                    self._last_request_at = time.monotonic()
                    raw = resp.read()
                    if resp.status != 200:
                        raise HttpError(f"HTTP {resp.status} for {url}", status=resp.status)
                    return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                self._last_request_at = time.monotonic()
                last_err = exc
                status = exc.code
                if status == 429 or status >= 500:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    wait = float(retry_after) if retry_after and str(retry_after).isdigit() else delay
                    wait = min(max(wait, 0.5), 30.0)
                    log.warning("HTTP %s on %s attempt %s/%s; backing off %.1fs", status, url, attempt, self.max_retries, wait)
                    time.sleep(wait)
                    delay = min(delay * 2, 30.0)
                    continue
                raise HttpError(f"HTTP {status} for {url}: {exc.reason}", status=status) from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                self._last_request_at = time.monotonic()
                last_err = exc
                log.warning("request failed %s attempt %s/%s: %s", url, attempt, self.max_retries, exc)
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
        raise HttpError(f"exhausted retries for {url}: {last_err}") from last_err
