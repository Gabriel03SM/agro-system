from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import HttpResponse
from django.db import connection, DatabaseError
from django.urls import include, path
from . import pwa

admin.site.site_header = "Administração · Agro Gestão"
admin.site.site_title = "Agro Gestão"


def healthz(request):
    return HttpResponse("ok")


def readyz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return HttpResponse("unavailable", status=503, content_type="text/plain")
    response = HttpResponse("ok", content_type="text/plain")
    response["Cache-Control"] = "no-store"
    return response


urlpatterns = [
    path("manifest.webmanifest", pwa.manifesto, name="manifesto"),
    path("service-worker.js", pwa.service_worker, name="service_worker"),
    path("offline/", pwa.offline, name="offline"),
    path("healthz", healthz),
    path("readyz", readyz, name="readyz"),
    path("admin/", admin.site.urls),
    path("entrar/", auth_views.LoginView.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("loja.urls")),
]
