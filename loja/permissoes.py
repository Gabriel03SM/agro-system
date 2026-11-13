from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def cargo_usuario(usuario):
    if not usuario.is_authenticated:
        return ""
    if usuario.is_staff or usuario.is_superuser:
        return "GERENTE"
    perfil = getattr(usuario, "perfil_loja", None)
    return perfil.cargo if perfil else "CAIXA"


def papel_required(*cargos):
    def decorate(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if cargo_usuario(request.user) not in cargos:
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return decorate


gerente_required = papel_required("GERENTE")
financeiro_required = papel_required("GERENTE", "CAIXA")
estoque_required = papel_required("GERENTE", "ESTOQUISTA")
