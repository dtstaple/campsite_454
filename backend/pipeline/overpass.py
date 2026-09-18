"""
Overpass API client.

Deliberately separate from any adapter. The framework binds one adapter to one model, so
OSM trails and OSM campsites have to be two adapters -- but they talk to the same service
in the same way, and that conversation should exist once. A campsites adapter reuses this
class unchanged.

Operating notes, verified against the live service rather than assumed:

* A descriptive User-Agent is mandatory. Without one the server answers HTTP 406, which
  is not a transient failure and must not be retried.
* The public instance allows 2 concurrent slots. Exceeding that produces error bodies
  rather than clean status codes, so retry-with-backoff is required, not optional.
* On overload Overpass serves an HTML error page with HTTP 200. A client that assumes a
  200 body is JSON will fail with a parse error far from the cause.
* Mirrors were unreachable during research, so none are hardcoded. The endpoint is
  injectable if that changes.

On polling /api/status before each request: not worth it. It reports free slots, but
costs an extra round trip per query and still races -- a slot can be taken between the
check and the request. Reacting to an actual rejection with backoff is simpler and
strictly more reliable. The status endpoint remains useful for debugging by hand.
"""

import logging
import time
from collections.abc import Callable

import requests

logger = logging.getLogger(__name__)

OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"

# Identifies the project to the service operators, as Overpass etiquette expects.
USER_AGENT = "CampSite-CIS454/0.1 (Syracuse University student project; TM05)"


class OverpassError(Exception):
    """Base for every failure this client raises."""


class OverpassUnavailable(OverpassError):
    """Transient: rate limited, overloaded, or unreachable. Retried, then given up on."""


class OverpassResponseError(OverpassError):
    """Permanent: the request or the response is wrong in a way retrying cannot fix."""


class OverpassClient:
    """A small, polite Overpass QL client."""

    # Statuses worth trying again. 429 is the documented rate-limit signal; the 5xx
    # family generally means the instance is briefly overloaded.
    RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})

    def __init__(
        self,
        *,
        endpoint: str = OVERPASS_ENDPOINT,
        user_agent: str = USER_AGENT,
        timeout_seconds: int = 180,
        max_attempts: int = 4,
        backoff_seconds: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.endpoint = endpoint
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep  # injectable so tests do not actually wait
        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent

    def query(self, overpass_ql: str) -> dict:
        """Run a query, retrying transient failures with exponential backoff."""
        last_failure: Exception | None = None

        for attempt in range(self.max_attempts):
            if attempt:
                delay = self.backoff_seconds * (2 ** (attempt - 1))
                logger.warning(
                    "Overpass unavailable (%s); retry %d of %d in %.0fs",
                    last_failure,
                    attempt + 1,
                    self.max_attempts,
                    delay,
                )
                self._sleep(delay)
            try:
                return self._attempt(overpass_ql)
            except OverpassUnavailable as exc:
                last_failure = exc

        raise OverpassUnavailable(
            f"Overpass still unavailable after {self.max_attempts} attempts. "
            f"The public instance allows 2 concurrent slots, so this usually means it is "
            f"busy rather than broken. Last failure: {last_failure}"
        )

    def _attempt(self, overpass_ql: str) -> dict:
        try:
            response = self._session.post(
                self.endpoint, data={"data": overpass_ql}, timeout=self.timeout_seconds
            )
        except requests.RequestException as exc:
            raise OverpassUnavailable(f"request to {self.endpoint} failed: {exc}") from exc

        if response.status_code == 406:
            raise OverpassResponseError(
                "Overpass returned HTTP 406 Not Acceptable, which means it rejected the "
                f"request headers rather than the query. User-Agent was {self.user_agent!r}. "
                "Retrying will not help; set a descriptive User-Agent."
            )

        if response.status_code in self.RETRYABLE_STATUSES:
            raise OverpassUnavailable(
                f"HTTP {response.status_code} from Overpass: {response.text[:200]}"
            )

        if response.status_code != 200:
            raise OverpassResponseError(
                f"Overpass returned HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError:
            # A 200 that is not JSON is Overpass serving an HTML error page under load.
            raise OverpassUnavailable(
                "Overpass returned a non-JSON body with HTTP 200, which it does when "
                f"overloaded. First 200 characters: {response.text[:200]!r}"
            ) from None

        if not isinstance(payload, dict) or "elements" not in payload:
            raise OverpassResponseError(
                "Overpass response has no 'elements' key; got "
                f"{sorted(payload) if isinstance(payload, dict) else type(payload).__name__}"
            )

        if "remark" in payload:
            # Overpass reports partial results and quota problems in a remark.
            logger.warning("Overpass remark: %s", payload["remark"])

        return payload
