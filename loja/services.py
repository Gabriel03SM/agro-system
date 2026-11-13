"""Regras de negócio que mexem em estoque. Tudo roda em transação."""
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import ItemVenda, MovimentoEstoque, Produto


class EstoqueInsuficiente(Exception):
    pass


def fmt_qtd(valor):
    return format(Decimal(valor).normalize(), "f")


def _travar(ids):
    return {p.pk: p for p in Produto.objects.select_for_update().filter(pk__in=ids)}


@transaction.atomic
def registrar_venda(venda, itens, usuario):
    """venda: Venda não salva. itens: lista de dicts (produto, quantidade, preco_unitario)."""
    necessario = defaultdict(Decimal)
    for i in itens:
        necessario[i["produto"].pk] += i["quantidade"]

    produtos = _travar(necessario.keys())
    for pk, qtd in necessario.items():
        p = produtos[pk]
        if p.estoque_atual < qtd:
            raise EstoqueInsuficiente(
                f"Estoque insuficiente de “{p.nome}”: disponível {fmt_qtd(p.estoque_atual)}, pedido {fmt_qtd(qtd)}."
            )

    venda.criado_por = usuario
    venda.total = sum((i["quantidade"] * i["preco_unitario"]).quantize(Decimal("0.01")) for i in itens)
    venda.save()

    for i in itens:
        ItemVenda.objects.create(venda=venda, produto=produtos[i["produto"].pk],
                                 quantidade=i["quantidade"], preco_unitario=i["preco_unitario"])

    for pk, qtd in necessario.items():
        p = produtos[pk]
        p.estoque_atual -= qtd
        p.save(update_fields=["estoque_atual"])
        MovimentoEstoque.objects.create(produto=p, quantidade=-qtd, motivo="VENDA", venda=venda, usuario=usuario)
    return venda


@transaction.atomic
def cancelar_venda(venda, usuario):
    if venda.cancelada:
        return venda
    soma = defaultdict(Decimal)
    for item in venda.itens.all():
        soma[item.produto_id] += item.quantidade
    produtos = _travar(soma.keys())
    for pk, qtd in soma.items():
        p = produtos[pk]
        p.estoque_atual += qtd
        p.save(update_fields=["estoque_atual"])
        MovimentoEstoque.objects.create(produto=p, quantidade=qtd, motivo="CANCELAMENTO",
                                        venda=venda, usuario=usuario)
    venda.cancelada = True
    venda.cancelada_em = timezone.now()
    venda.save(update_fields=["cancelada", "cancelada_em"])
    return venda


@transaction.atomic
def ajustar_estoque(produto, tipo, quantidade, observacao, usuario):
    """tipo: ENTRADA (soma), PERDA (subtrai) ou AJUSTE (define o estoque para 'quantidade')."""
    p = Produto.objects.select_for_update().get(pk=produto.pk)
    if tipo == "ENTRADA":
        delta = quantidade
    elif tipo == "PERDA":
        if p.estoque_atual < quantidade:
            raise EstoqueInsuficiente(f"Estoque atual ({fmt_qtd(p.estoque_atual)}) é menor que a perda informada.")
        delta = -quantidade
    else:
        delta = quantidade - p.estoque_atual
    if delta == 0:
        return p
    p.estoque_atual += delta
    p.save(update_fields=["estoque_atual"])
    MovimentoEstoque.objects.create(produto=p, quantidade=delta, motivo=tipo, observacao=observacao, usuario=usuario)
    return p
