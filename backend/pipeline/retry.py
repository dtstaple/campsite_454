"""
Retry with exponential backoff.

Every remote source needs this and none of them need a different version of it. The
protocol-specific part is deciding *which* failures are worth retrying; that stays with
the caller, which passes the exception type it considers transient.
"""

import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


def call_with_backoff(
    operation: Callable[[], object],
    *,
    retry_on: type[Exception] | tuple[type[Exception], ...],
    on_exhausted: Callable[[Exception], Exception] | None = None,
    max_attempts: int = 4,
    backoff_seconds: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
    describe: str = "request",
):
    """Call `operation`, retrying `retry_on` failures with doubling delays.

    Delays are backoff_seconds, then double each attempt: 5s, 10s, 20s by default.
    `sleep` is injectable so tests never actually wait.

    When every attempt fails, `on_exhausted` builds the exception to raise from the last
    failure -- letting each caller phrase the give-up message in its own terms. Without
    it the last failure is re-raised as is.
    """
    last_failure: Exception | None = None

    for attempt in range(max_attempts):
        if attempt:
            delay = backoff_seconds * (2 ** (attempt - 1))
            logger.warning(
                "%s failed (%s); retry %d of %d in %.0fs",
                describe,
                last_failure,
                attempt + 1,
                max_attempts,
                delay,
            )
            sleep(delay)
        try:
            return operation()
        except retry_on as exc:
            last_failure = exc

    if on_exhausted is not None:
        raise on_exhausted(last_failure)
    raise last_failure
