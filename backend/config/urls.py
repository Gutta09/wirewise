from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"status": "ok", "app": "Wirewise"})


urlpatterns = [
    path("api/health", health, name="health"),
    path("api/", include("reconciliation.api.urls")),
    path("admin/", admin.site.urls),
]
