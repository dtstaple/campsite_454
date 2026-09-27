"""
Registration, login, and saved-campsite endpoints.

Registration deliberately returns the same 201 response whether the email is fresh or
already belongs to another account, and simply skips creating a second row in the
latter case. Anything else -- a distinct error, a different status code -- would let an
attacker use this endpoint to check whether an email address has an account here.

Login treats "no such user" and "wrong password" identically: authenticate() returns
None for both (Django's ModelBackend runs a dummy password hash for the former so the
two cases don't even time differently), so there is nothing extra to special-case here.
"""

from django.contrib.auth import authenticate, get_user_model
from django.http import Http404
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from geodata.models import Campsite

from .models import SavedCampsite
from .serializers import RegisterSerializer

User = get_user_model()


@api_view(["POST"])
@permission_classes([AllowAny])
def register_view(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    username = serializer.validated_data["username"]
    email = serializer.validated_data["email"]

    if not User.objects.filter(email__iexact=email).exists():
        serializer.save()

    return Response({"username": username, "email": email}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    username = request.data.get("username", "")
    password = request.data.get("password", "")

    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response({"error": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key})


@api_view(["POST", "DELETE"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def saved_campsite_view(request, source_id):
    """Save or unsave the campsite with this source_id.

    Keyed on source_id rather than the primary key because source_id is what the map API
    already puts in each GeoJSON Feature's `id`, and it is the identifier that survives.
    The primary key is an internal artefact that a rebuild renumbers; source_id is the
    upsert key every adapter loads on, so it still points at the same real campsite after
    a re-ingest. A saved campsite has to outlive both.

    Uniqueness in the database is on (source, source_id), so source_id alone is unique
    only because each source namespaces its ids with its own prefix -- "campsite/" from
    RIDB, "node/" and "way/" from OSM. first() keeps that assumption from turning into a
    500 if a future source ever breaks it.
    """
    campsite = Campsite.objects.filter(source_id=source_id).order_by("pk").first()
    if campsite is None:
        raise Http404(f"No campsite with source_id {source_id!r}")

    if request.method == "POST":
        _, created = SavedCampsite.objects.get_or_create(user=request.user, campsite=campsite)
        return Response(status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    deleted, _ = SavedCampsite.objects.filter(user=request.user, campsite=campsite).delete()
    if not deleted:
        return Response(status=status.HTTP_404_NOT_FOUND)
    return Response(status=status.HTTP_204_NO_CONTENT)
