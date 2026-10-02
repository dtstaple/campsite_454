from django.urls import path

from api.campsite_detail import campsite_detail_view
from api.routes import route_detail_view, routes_view
from api.views import layer_view, map_data_view

urlpatterns = [
    path("map-data/", map_data_view, name="map-data"),
    path("campsites/", layer_view, {"layer": "campsites"}, name="campsites"),
    # <path:> because a source_id contains a slash; the trailing /detail/ anchors it.
    path("campsites/<path:source_id>/detail/", campsite_detail_view, name="campsite-detail"),
    path("trails/", layer_view, {"layer": "trails"}, name="trails"),
    path("water/", layer_view, {"layer": "water"}, name="water"),
    path("public-land/", layer_view, {"layer": "public-land"}, name="public-land"),
    path("routes/", routes_view, name="routes"),
    path("routes/<int:osm_id>/", route_detail_view, name="route-detail"),
]
