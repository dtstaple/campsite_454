from django.urls import path

from .candidate_views import route_candidates_view, way_candidates_view
from .hike_views import hike_gpx_view, hike_view, hikes_view
from .plan_views import (
    plan_auto_view,
    plan_gpx_view,
    plan_preview_view,
    plan_view,
    plans_view,
)
from .saved_trail_views import saved_trail_view, saved_trails_view
from .views import waypoint_view, waypoints_view

urlpatterns = [
    path("waypoints/", waypoints_view, name="waypoints"),
    path("waypoints/<int:pk>/", waypoint_view, name="waypoint"),
    path("saved-trails/", saved_trails_view, name="saved-trails"),
    path("saved-trails/<int:pk>/", saved_trail_view, name="saved-trail"),
    path("hikes/", hikes_view, name="hikes"),
    path("hikes/<int:pk>/", hike_view, name="hike"),
    path("hikes/<int:pk>/gpx/", hike_gpx_view, name="hike-gpx"),
    path("plans/", plans_view, name="plans"),
    path("plans/preview/", plan_preview_view, name="plan-preview"),
    path("plans/auto/", plan_auto_view, name="plan-auto"),
    path("plans/<int:pk>/", plan_view, name="plan"),
    path("plans/<int:pk>/gpx/", plan_gpx_view, name="plan-gpx"),
    path("routes/<int:osm_id>/candidates/", route_candidates_view, name="route-candidates"),
    # <path:> because a way's source_id contains a slash; /candidates/ anchors it.
    path("trails/<path:source_id>/candidates/", way_candidates_view, name="way-candidates"),
]
