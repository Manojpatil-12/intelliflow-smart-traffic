from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard_view, name="home"),
    path("api/weather/", views.weather_api, name="weather_api"),
]
