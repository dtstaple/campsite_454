"""
Rate limits on login and register (TM05-88): DRF's ScopedRateThrottle, per client IP, with
the rates in settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] (docs/auth.md).

Scoped rather than a default throttle so only these two endpoints are limited: the map,
the panel and everything a signed-in user does are untouched. DRF has no decorator for a
function view's scope, so `throttle_scope()` sets it on the view class @api_view built.

Over the limit is a 429 with a Retry-After header, and this module's exception handler
gives it the API's usual {"error": ...} body with a sentence a person can act on.
"""

import math

from rest_framework.exceptions import Throttled
from rest_framework.views import exception_handler as drf_exception_handler

LOGIN = "auth-login"
REGISTER = "auth-register"
#: TM05-170: the natural-language trip finder, which can call a paid model.
DISCOVER_INTERPRET = "discover-interpret"

MESSAGES = {
    LOGIN: "Too many login attempts from this address.",
    REGISTER: "Too many accounts created from this address.",
    DISCOVER_INTERPRET: "Too many trip descriptions from this address.",
}


def throttle_scope(scope: str):
    """Decorator, above @api_view: rate-limit the view under `scope`."""

    def apply(view):
        view.cls.throttle_scope = scope
        return view

    return apply


def exception_handler(exc, context):
    """DRF's handler, with a readable body for a throttled login or register."""
    response = drf_exception_handler(exc, context)
    scope = getattr(context.get("view"), "throttle_scope", None)
    if isinstance(exc, Throttled) and response is not None and scope in MESSAGES:
        wait = math.ceil(exc.wait) if exc.wait is not None else None
        retry = f" Try again in {wait} seconds." if wait is not None else " Try again later."
        response.data = {"error": MESSAGES[scope] + retry, "retry_after_s": wait}
    return response
