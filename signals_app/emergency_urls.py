from django.urls import path

from . import views

app_name = "emergency"

urlpatterns = [
    path("", views.emergency_list, name="emergency_list"),
    path("create/", views.emergency_create, name="emergency_create"),
    path("<int:pk>/resolve/", views.emergency_resolve, name="emergency_resolve"),
]
