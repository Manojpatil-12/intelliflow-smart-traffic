from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("map/", include("core.urls")),
    path("prediction/", include("prediction.urls")),
    path("routing/", include("routing.urls")),
    path("signals/", include("signals_app.urls")),
    path("emergency/", include("signals_app.emergency_urls")),
    path("vision/", include("vision.urls")),
    path("analytics/", include("dashboard.analytics_urls")),
    path("api/", include("core.api_urls")),
    path("", lambda r: redirect("dashboard:home")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "IntelliFlow Administration"
admin.site.site_title = "IntelliFlow Admin"
admin.site.index_title = "Traffic Prediction Management"
