from django.urls import path, re_path

from .views import plan_route_view, planned_candidates_view, planned_gpx_view, planned_route_view

# <region>:<cost>:<node>,<node>,... (routing/service.py, ROUTE_ID)
# A stop is an OSM node id, or w<way>-<decimetres along it> (TM05-137).
ROUTE_ID = r"(?P<route_id>[a-z0-9-]+:[a-z]+:(?:w\d+-\d+|\d+)(?:,(?:w\d+-\d+|\d+))+)"

urlpatterns = [
    path("routing/plan/", plan_route_view, name="routing-plan"),
    re_path(rf"^routing/{ROUTE_ID}/$", planned_route_view, name="routing-route"),
    re_path(
        rf"^routing/{ROUTE_ID}/candidates/$", planned_candidates_view, name="routing-candidates"
    ),
    re_path(rf"^routing/{ROUTE_ID}/gpx/$", planned_gpx_view, name="routing-gpx"),
]
