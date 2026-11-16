"""
Shareable trip plan links (TM05-172). Contract: docs/api.md, "Sharing a plan".

    POST   /api/plans/<id>/share/   the owner turns sharing on; returns the token
    DELETE /api/plans/<id>/share/   the owner revokes the link
    GET    /api/shared/<token>/     anyone with the link: the plan, read-only, no sign-in

The token is long and random (secrets.token_urlsafe, 256 bits), so a link can't be
guessed. Revoking clears it: the old link is a 404 from then on, and sharing again makes a
new token. The shared view carries the route, the nights and the daily stats, and nothing
about the owner: no username, email or plan id, and none of the owner's waypoints.
"""

import secrets

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import TripPlan
from .plan_views import _public, _work_out
from .plans import PlanError

TOKEN_BYTES = 32


def share_payload(plan: TripPlan) -> dict:
    return {"token": plan.share_token, "path": f"/shared/{plan.share_token}"}


@api_view(["POST", "DELETE"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def plan_share_view(request, pk: int):
    plan = get_object_or_404(TripPlan, pk=pk, user=request.user)
    if request.method == "DELETE":
        plan.share_token = None
        plan.save(update_fields=["share_token"])
        return Response(status=status.HTTP_204_NO_CONTENT)
    if plan.share_token:
        return Response(share_payload(plan))
    plan.share_token = secrets.token_urlsafe(TOKEN_BYTES)
    plan.save(update_fields=["share_token"])
    return Response(share_payload(plan), status=status.HTTP_201_CREATED)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def shared_plan_view(request, token: str):
    plan = get_object_or_404(TripPlan, share_token=token)
    try:
        worked = _public(_work_out(plan))
    except PlanError as error:
        return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"name": plan.name, "trail_name": plan.trail_name, **worked})
