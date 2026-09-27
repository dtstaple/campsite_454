from django.urls import path

from .views import login_view, register_view, saved_campsite_view

urlpatterns = [
    path("auth/register/", register_view),
    path("auth/login/", login_view),
    # <path:> rather than <str:>: a campsite source_id contains a slash
    # ("campsite/73996"), which <str:> refuses to match.
    path("saved-campsites/<path:source_id>/", saved_campsite_view),
]
