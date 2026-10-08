from django.urls import path

from .views import waypoint_view, waypoints_view

urlpatterns = [
    path("waypoints/", waypoints_view, name="waypoints"),
    path("waypoints/<int:pk>/", waypoint_view, name="waypoint"),
]
