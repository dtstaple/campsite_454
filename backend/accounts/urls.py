from django.urls import path

from .views import login_view, register_view, saved_campsite_view

urlpatterns = [
    path("auth/register/", register_view),
    path("auth/login/", login_view),
    path("saved-campsites/<int:campsite_id>/", saved_campsite_view),
]
