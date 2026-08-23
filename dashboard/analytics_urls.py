from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("", views.analytics_view, name="analytics"),
    path("api/whatif/", views.whatif_predict_api, name="whatif_api"),
]
