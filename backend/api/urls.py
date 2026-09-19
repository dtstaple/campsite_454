from django.urls import path

from api.views import layer_view, map_data_view

urlpatterns = [
    path("map-data/", map_data_view, name="map-data"),
    path("campsites/", layer_view, {"layer": "campsites"}, name="campsites"),
    path("trails/", layer_view, {"layer": "trails"}, name="trails"),
    path("water/", layer_view, {"layer": "water"}, name="water"),
]
