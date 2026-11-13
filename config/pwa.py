import hashlib
import json

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static


def manifesto(request):
    return JsonResponse({"id": "/", "name": settings.NOME_LOJA, "short_name": "Agro Gestão", "lang": "pt-BR",
        "start_url": "/", "scope": "/", "display": "standalone", "background_color": "#f4f6f3", "theme_color": "#2f6b3a",
        "icons": [{"src": static(f"icons/agro-{tamanho}.png"), "sizes": f"{tamanho}x{tamanho}",
                   "type": "image/png", "purpose": "any maskable"} for tamanho in (192, 512)]},
        content_type="application/manifest+json")


def service_worker(request):
    assets = ["/offline/", static("css/app.css"), static("js/app.js"), static("icons/agro-192.png"), static("icons/agro-512.png")]
    versao = hashlib.sha256(json.dumps(assets).encode()).hexdigest()[:12]
    response = render(request, "service_worker.js", {"assets": json.dumps(assets), "versao": versao}, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


def offline(request):
    return render(request, "offline.html", {"NOME_LOJA": settings.NOME_LOJA})
