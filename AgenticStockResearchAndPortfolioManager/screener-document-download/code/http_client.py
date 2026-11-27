"""HTTP client with polite random delays and retry/backoff."""
from __future__ import annotations

import logging
import random
import time
from typing import Optional

import requests

from config import LOGGER_NAME, MAX_RETRIES, REQUEST_TIMEOUT, RETRYABLE_STATUS

log = logging.getLogger(LOGGER_NAME)


class Fetcher:
    def __init__(self, session: requests.Session, min_delay: float, max_delay: float):
        self.session = session
        self.min_delay = min_delay
        self.max_delay = max_delay

    def _sleep(self) -> None:
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._sleep()
            try:
                resp = self.session.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            except requests.RequestException as exc:
                last_exc = exc
                log.warning("Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, url, exc)
            else:
                if resp.status_code not in RETRYABLE_STATUS:
                    return resp
                last_exc = requests.HTTPError(f"HTTP {resp.status_code}")
                log.warning("Attempt %d/%d got HTTP %d for %s",
                            attempt, MAX_RETRIES, resp.status_code, url)
                resp.close()
            time.sleep(2 ** attempt)  # exponential backoff on top of the polite delay
        raise requests.RequestException(f"Giving up on {url}: {last_exc}")
