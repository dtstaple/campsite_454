from django.urls import path

from .views import interpret_view

urlpatterns = [
    path("discover/interpret/", interpret_view, name="discover-interpret"),
]
