from django.urls import path

from . import views

app_name = "routing"

urlpatterns = [
    path("", views.route_planner, name="route_planner"),
    path("api/geocode/", views.api_geocode, name="api_geocode"),
    path("api/route/", views.api_route, name="api_route"),
]
