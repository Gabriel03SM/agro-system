from contextvars import ContextVar
from functools import wraps
from inspect import signature

from django.db.models.signals import post_delete, post_save, pre_save

autor = ContextVar("autor_auditoria", default=None)


class AuditoriaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = autor.set(request.user if request.user.is_authenticated else None)
        try:
            return self.get_response(request)
        finally:
            autor.reset(token)


def com_usuario(func):
    assinatura = signature(func)

    @wraps(func)
    def wrapper(*args, **kwargs):
        usuario = assinatura.bind(*args, **kwargs).arguments.get("usuario")
        token = autor.set(usuario or autor.get())
        try:
            return func(*args, **kwargs)
        finally:
            autor.reset(token)
    return wrapper


def snapshot(instance):
    resultado = {}
    for field in instance._meta.concrete_fields:
        if field.name in ("password", "last_login"):
            continue
        valor = getattr(instance, field.attname)
        resultado[field.attname] = valor if isinstance(valor, (bool, int, float, type(None))) else str(valor)
    return resultado


def antes_salvar(sender, instance, raw=False, **kwargs):
    if raw:
        return
    anterior = sender.objects.filter(pk=instance.pk).first() if instance.pk else None
    instance._antes_auditoria = snapshot(anterior) if anterior else {}


def apos_salvar(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    from .models import RegistroAuditoria
    antes = getattr(instance, "_antes_auditoria", {})
    depois = snapshot(instance)
    if antes == depois:
        return
    RegistroAuditoria.objects.create(usuario=autor.get(), modelo=instance._meta.label,
        objeto_id=str(instance.pk), acao="CRIAR" if created else "ALTERAR", antes=antes, depois=depois)


def apos_excluir(sender, instance, **kwargs):
    from .models import RegistroAuditoria
    RegistroAuditoria.objects.create(usuario=autor.get(), modelo=instance._meta.label,
        objeto_id=str(instance.pk), acao="EXCLUIR", antes=snapshot(instance))


def conectar():
    from django.contrib.auth import get_user_model
    from .models import (AlteracaoVenda, Categoria, Cliente, ContaPagar, Fornecedor, ItemVenda, LoteProduto, MovimentoCaixa,
                         MovimentoEstoque, PagamentoConta, PagamentoVenda, PerfilUsuario, Produto, RecebimentoFiado, SessaoCaixa, Venda)
    for model in (get_user_model(), AlteracaoVenda, Categoria, Cliente, ContaPagar, Fornecedor, LoteProduto,
                  ItemVenda, MovimentoCaixa, MovimentoEstoque, PagamentoConta, PagamentoVenda, PerfilUsuario, Produto, RecebimentoFiado, SessaoCaixa, Venda):
        chave = model._meta.label
        pre_save.connect(antes_salvar, sender=model, dispatch_uid=f"auditar_antes_{chave}")
        post_save.connect(apos_salvar, sender=model, dispatch_uid=f"auditar_depois_{chave}")
        post_delete.connect(apos_excluir, sender=model, dispatch_uid=f"auditar_excluir_{chave}")
