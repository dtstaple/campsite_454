"""
Saved trails (TM05-100). Contract: docs/api.md, "Saved trails".

    GET    /api/saved-trails/        the user's saved trails, newest first
    POST   /api/saved-trails/        save one: {osm_id} or {from_way}; saving twice is 200
    DELETE /api/saved-trails/<id>/   unsave it

Token-authenticated; every query starts from request.user, as for waypoints and plans.
The trail is resolved when saved, so a name and length are on hand for the Profile list
without resolving every trail again.
"""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import SavedTrail
from .plan_views import _resolve_trail
from .plans import PlanError

MAX_SAVED_TRAILS = 500


def _payload(saved: SavedTrail) -> dict:
    return {
        "id": saved.id,
        "osm_id": saved.osm_id,
        "from_way": saved.from_way or None,
        "name": saved.name,
        "length_m": round(saved.length_m, 1) if saved.length_m is not None else None,
        "created_at": saved.created_at,
    }


@api_view(["GET", "POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def saved_trails_view(request):
    mine = SavedTrail.objects.filter(user=request.user)
    if request.method == "GET":
        return Response([_payload(saved) for saved in mine])

    try:
        route = _resolve_trail(request.data.get("osm_id"), request.data.get("from_way"))
    except PlanError as error:
        return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
    if route.osm_id is not None:
        existing = mine.filter(osm_id=route.osm_id).first()
        identity = {"osm_id": route.osm_id}
    else:
        from_way = str(request.data.get("from_way"))
        existing = mine.filter(osm_id__isnull=True, from_way=from_way).first()
        identity = {"from_way": from_way}
    if existing:
        return Response(_payload(existing), status=status.HTTP_200_OK)
    if mine.count() >= MAX_SAVED_TRAILS:
        return Response(
            {"error": f"You can keep up to {MAX_SAVED_TRAILS} saved trails."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    saved = SavedTrail.objects.create(
        user=request.user, name=route.name, length_m=route.length_m, **identity
    )
    return Response(_payload(saved), status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def saved_trail_view(request, pk: int):
    get_object_or_404(SavedTrail, pk=pk, user=request.user).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
