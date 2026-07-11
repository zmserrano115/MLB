import logging
import os
from threading import Lock, Semaphore
import time

import requests


LOGGER = logging.getLogger(__name__)

APP_USER_AGENT = os.environ.get(
    "ALL_RISE_USER_AGENT",
    "AllRiseAnalytics/1.0 (https://allriseanalytics.streamlit.app)",
)
DEFAULT_TIMEOUT = 20
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}
MAX_CONCURRENCY = max(
    1,
    int(os.environ.get("ALL_RISE_HTTP_MAX_CONCURRENCY", "8") or 8),
)
MIN_INTERVAL_SECONDS = max(
    0.0,
    float(os.environ.get("ALL_RISE_HTTP_MIN_INTERVAL_SECONDS", "0") or 0),
)

_SESSION = None
_SESSION_LOCK = Lock()
_CONCURRENCY = Semaphore(MAX_CONCURRENCY)
_RATE_LOCK = Lock()
_LAST_REQUEST_AT = 0.0


def session():
    global _SESSION
    if _SESSION is None:
        with _SESSION_LOCK:
            if _SESSION is None:
                http = requests.Session()
                http.headers.update(
                    {
                        "Accept": "application/json",
                        "User-Agent": APP_USER_AGENT,
                    }
                )
                _SESSION = http
    return _SESSION


def _merged_headers(headers=None):
    merged = {"User-Agent": APP_USER_AGENT}
    if headers:
        merged.update(headers)
    return merged


def _respect_rate_limit():
    if MIN_INTERVAL_SECONDS <= 0:
        return

    global _LAST_REQUEST_AT
    with _RATE_LOCK:
        now = time.monotonic()
        wait_for = MIN_INTERVAL_SECONDS - (now - _LAST_REQUEST_AT)
        if wait_for > 0:
            time.sleep(wait_for)
        _LAST_REQUEST_AT = time.monotonic()


def request(
    method,
    url,
    *,
    provider=None,
    timeout=DEFAULT_TIMEOUT,
    attempts=3,
    backoff=0.45,
    headers=None,
    session_obj=None,
    **kwargs,
):
    http = session_obj or session()
    attempts = max(1, int(attempts or 1))
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            _respect_rate_limit()
            with _CONCURRENCY:
                response = http.request(
                    method,
                    url,
                    timeout=timeout,
                    headers=_merged_headers(headers),
                    **kwargs,
                )
            if (
                response.status_code in TRANSIENT_STATUSES
                and attempt < attempts
            ):
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else backoff * attempt
                except (TypeError, ValueError):
                    delay = backoff * attempt
                LOGGER.warning(
                    "%s request to %s returned %s; retrying in %.2fs",
                    provider or "HTTP",
                    url,
                    response.status_code,
                    delay,
                )
                time.sleep(delay)
                continue
            return response
        except requests.RequestException as error:
            last_error = error
            if attempt >= attempts:
                LOGGER.warning(
                    "%s request to %s failed: %s",
                    provider or "HTTP",
                    url,
                    error,
                )
                raise
            delay = backoff * attempt
            LOGGER.warning(
                "%s request to %s failed: %s; retrying in %.2fs",
                provider or "HTTP",
                url,
                error,
                delay,
            )
            time.sleep(delay)

    raise last_error


def get(url, **kwargs):
    return request("GET", url, **kwargs)


def get_json(url, **kwargs):
    response = get(url, **kwargs)
    response.raise_for_status()
    return response.json()
