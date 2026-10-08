"""
Waypoint endpoints (TM05-80).

    GET    /api/waypoints/          the signed-in user's waypoints
    POST   /api/waypoints/          create one
    GET    /api/waypoints/<id>/     one of them
    PATCH  /api/waypoints/<id>/     rename, retype, move, or edit the note
    DELETE /api/waypoints/<id>/     delete it

Token-authenticated like the saved-campsite endpoints (accounts/views.py). Every query
starts from Waypoint.objects.filter(user=request.user), so another user's waypoint is
simply not found: 404, never 403, which would confirm that the id exists.
"""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Waypoint
from .serializers import WaypointSerializer

#: Generous for a person's own marks, and a bound on what one account can store.
MAX_WAYPOINTS_PER_USER = 1000


@api_view(["GET", "POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def waypoints_view(request):
    mine = Waypoint.objects.filter(user=request.user)
    if request.method == "GET":
        return Response(WaypointSerializer(mine, many=True).data)

    if mine.count() >= MAX_WAYPOINTS_PER_USER:
        return Response(
            {"error": f"You can keep up to {MAX_WAYPOINTS_PER_USER} waypoints."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    serializer = WaypointSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save(user=request.user)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def waypoint_view(request, pk: int):
    waypoint = get_object_or_404(Waypoint, pk=pk, user=request.user)
    if request.method == "DELETE":
        waypoint.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == "PATCH":
        serializer = WaypointSerializer(waypoint, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
    return Response(WaypointSerializer(waypoint).data)
