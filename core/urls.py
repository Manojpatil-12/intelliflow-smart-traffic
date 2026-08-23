from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.map_view, name="map"),
    path("intersections/", views.intersection_list, name="intersection_list"),
    path("intersections/<int:pk>/", views.intersection_detail, name="intersection_detail"),
]
