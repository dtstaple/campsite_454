from django.urls import path

from .candidate_views import route_candidates_view, way_candidates_view
from .plan_views import plan_gpx_view, plan_preview_view, plan_view, plans_view
from .views import waypoint_view, waypoints_view

urlpatterns = [
    path("waypoints/", waypoints_view, name="waypoints"),
    path("waypoints/<int:pk>/", waypoint_view, name="waypoint"),
    path("plans/", plans_view, name="plans"),
    path("plans/preview/", plan_preview_view, name="plan-preview"),
    path("plans/<int:pk>/", plan_view, name="plan"),
    path("plans/<int:pk>/gpx/", plan_gpx_view, name="plan-gpx"),
    path("routes/<int:osm_id>/candidates/", route_candidates_view, name="route-candidates"),
    # <path:> because a way's source_id contains a slash; /candidates/ anchors it.
    path("trails/<path:source_id>/candidates/", way_candidates_view, name="way-candidates"),
]
