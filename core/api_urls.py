from django.urls import path

from . import api_views

urlpatterns = [
    path("predictions/latest/", api_views.latest_predictions, name="api_latest_predictions"),
    path("intersections/", api_views.intersection_list_api, name="api_intersections"),
]
