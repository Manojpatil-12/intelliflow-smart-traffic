from django.urls import path

from . import views

app_name = "signals_app"

urlpatterns = [
    path("", views.signals_list, name="signals_list"),
    path("<int:pk>/override/", views.signal_override, name="signal_override"),
]
