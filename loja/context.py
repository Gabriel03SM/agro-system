from django.conf import settings
from .permissoes import cargo_usuario


def loja(request):
    cargo = cargo_usuario(request.user)
    return {"NOME_LOJA": settings.NOME_LOJA, "cargo_usuario": cargo, "pode_gerir": cargo == "GERENTE",
            "pode_estoque": cargo in ("GERENTE", "ESTOQUISTA"), "pode_financeiro": cargo in ("GERENTE", "CAIXA")}
