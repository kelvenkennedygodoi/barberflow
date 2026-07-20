from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path


def saude(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "indisponivel"}, status=503)
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("saude/", saude, name="saude"),
    path("admin/", admin.site.urls),
    path(
        "entrar/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("gestao.urls")),
]
