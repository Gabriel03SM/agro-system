from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import HttpResponse
from django.urls import include, path

admin.site.site_header = "Administração · Agro Gestão"
admin.site.site_title = "Agro Gestão"


def healthz(request):
    return HttpResponse("ok")


urlpatterns = [
    path("healthz", healthz),
    path("admin/", admin.site.urls),
    path("entrar/", auth_views.LoginView.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("loja.urls")),
]
