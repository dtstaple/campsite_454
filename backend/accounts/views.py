"""
Registration, login, account deletion, and saved-campsite endpoints.

Registration deliberately returns the same 201 response whether the email is fresh or
already belongs to another account, and simply skips creating a second row in the
latter case. Anything else -- a distinct error, a different status code -- would let an
attacker use this endpoint to check whether an email address has an account here.

Login treats "no such user" and "wrong password" identically: authenticate() returns
None for both (Django's ModelBackend runs a dummy password hash for the former so the
two cases don't even time differently), so there is nothing extra to special-case here.

Logout deletes the token row rather than marking it inactive. DRF tokens carry no expiry
and no refresh flow, so the row's existence *is* the session -- deleting it is the only
thing that actually revokes access. A client that keeps using the old token gets 401 from
then on, which is what "signed out" has to mean on the server and not just in localStorage.

Account deletion relies on CASCADE alone. Every foreign key to the user cascades: the auth
token (DRF's Token.user), saved campsites (SavedCampsite.user) and Django's own admin log;
group and permission memberships are many-to-many rows Django removes with the user. A
test walks the user model's relations, so a future non-cascading key fails CI rather than
leaving orphans behind.
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
from .serializers import RegisterSerializer, SavedCampsiteSerializer

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


@api_view(["POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """Revoke the token this request was made with.

    request.auth is the Token row TokenAuthentication resolved, so this deletes exactly
    the credential the caller presented. POST rather than GET: it changes server state,
    and a GET would be followable by a link prefetch.

    204 with no body -- there is nothing to tell the client except that it worked, and
    logging out twice is not an error worth reporting: the second call simply 401s,
    because the token is already gone.
    """
    request.auth.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET", "DELETE"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def current_user_view(request):
    """GET: who does this token belong to. DELETE: delete that account.

    GET has the same shape as the registration response (username, email) so a client has
    one idea of what an account looks like. The user's primary key is deliberately not
    included: no other endpoint exposes an internal row id, and nothing the frontend does
    needs one.

    DELETE removes the user, and with it, by CASCADE, their token and saved campsites
    (see the module docstring). It acts only on request.user -- there is no id in the URL
    -- so no request can reach another account. 204 with no body; the token is gone, so
    every later request with it is a 401.
    """
    if request.method == "DELETE":
        request.user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    return Response({"username": request.user.username, "email": request.user.email})


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


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def saved_campsites_view(request):
    """Every campsite this user has saved, newest first.

    Scoped to request.user, so the filter is the whole of the authorisation story -- there
    is no id in the URL that could be tampered with to reach someone else's list.

    select_related because the serializer reads through to campsite on every row; without
    it a user with thirty saves costs thirty-one queries.

    order_by repeats what SavedCampsite.Meta already says. It is spelled out because the
    frontend renders these in order and that ordering should not quietly change if the
    model's default is ever edited for some other caller's benefit.
    """
    saved = (
        SavedCampsite.objects.filter(user=request.user)
        .select_related("campsite")
        .order_by("-created_at")
    )
    return Response(SavedCampsiteSerializer(saved, many=True).data)
