from django.conf import settings


def loja(request):
    return {"NOME_LOJA": settings.NOME_LOJA}
