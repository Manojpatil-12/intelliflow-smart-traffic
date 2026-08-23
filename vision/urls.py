from django.urls import path

from . import views

app_name = "vision"

urlpatterns = [
    path("", views.vision_upload, name="vision_upload"),
    path("api/detect/", views.vision_detect_api, name="vision_detect_api"),
]
