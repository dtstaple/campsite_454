"""
POST /api/discover/interpret/ (TM05-170). Contract: docs/api.md, "Natural-language trip
finder". Public, like the trail search it feeds, and rate-limited per client IP under the
`discover-interpret` scope (settings.REST_FRAMEWORK, accounts/throttling.py).
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from accounts.throttling import DISCOVER_INTERPRET, throttle_scope

from .interpret import MAX_TEXT_CHARS, interpret


@throttle_scope(DISCOVER_INTERPRET)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def interpret_view(request):
    text = request.data.get("text") if isinstance(request.data, dict) else None
    if not isinstance(text, str) or not text.strip():
        return Response(
            {"error": "Describe the trip you want, e.g. two nights, lakeside, moderate climb."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    text = " ".join(text.split())
    if len(text) > MAX_TEXT_CHARS:
        return Response(
            {"error": f"Keep it under {MAX_TEXT_CHARS} characters."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response(interpret(text))
