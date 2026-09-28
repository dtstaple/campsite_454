from django.urls import path

from .views import (
    current_user_view,
    login_view,
    logout_view,
    register_view,
    saved_campsite_view,
    saved_campsites_view,
)

urlpatterns = [
    path("auth/register/", register_view),
    path("auth/login/", login_view),
    path("auth/logout/", logout_view),
    path("auth/me/", current_user_view),
    # The list route sits above the detail route below it. <path:> matches greedily across
    # slashes, so keeping the bare collection URL first means it can never be swallowed as
    # a source_id. (It would not match an empty remainder today, but the ordering makes
    # that a choice rather than an accident.)
    path("saved-campsites/", saved_campsites_view),
    # <path:> rather than <str:>: a campsite source_id contains a slash
    # ("campsite/73996"), which <str:> refuses to match.
    path("saved-campsites/<path:source_id>/", saved_campsite_view),
]
