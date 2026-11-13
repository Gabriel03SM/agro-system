from decimal import Decimal, ROUND_HALF_UP

from django.db.models import F, Q
from django.utils import timezone

from .models import ConsumoLote, LoteProduto

ZERO = Decimal("0")


def consumir(item):
    from .services import RegraNegocio
    if not item.produto.controla_lote:
        return
    lotes = LoteProduto.objects.select_for_update().filter(produto=item.produto, quantidade__gt=0).filter(
        Q(validade__isnull=True) | Q(validade__gte=timezone.localdate())).order_by(F("validade").asc(nulls_last=True), "pk")
    restante, custo = item.quantidade, ZERO
    for lote in lotes:
        qtd = min(restante, lote.quantidade)
        ConsumoLote.objects.create(item=item, lote=lote, quantidade=qtd, custo_unitario=lote.custo_unitario)
        lote.quantidade -= qtd
        lote.save(update_fields=["quantidade"])
        custo += qtd * lote.custo_unitario
        restante -= qtd
        if restante == ZERO:
            break
    if restante > ZERO:
        raise RegraNegocio(f"Não há saldo suficiente em lotes válidos de “{item.produto.nome}”. Confira os vencimentos.")
    item.preco_custo = (custo / item.quantidade).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    item.save(update_fields=["preco_custo"])


def devolver(venda):
    for item in venda.itens.select_related("produto").prefetch_related("consumos_lote"):
        consumos = list(item.consumos_lote.all())
        if consumos:
            for consumo in sorted(consumos, key=lambda c: c.lote_id):
                lote = LoteProduto.objects.select_for_update().get(pk=consumo.lote_id)
                lote.quantidade += consumo.quantidade
                lote.save(update_fields=["quantidade"])
        elif item.produto.controla_lote:
            lote, _ = LoteProduto.objects.get_or_create(produto=item.produto, numero=f"DEVOLUCAO-{venda.pk}",
                defaults={"custo_unitario": item.preco_custo or item.produto.preco_custo})
            lote.quantidade += item.quantidade
            lote.save(update_fields=["quantidade"])


def ajustar_lote(produto, tipo, quantidade, custo, lote=None, numero="", validade=None):
    from .services import RegraNegocio
    if tipo == "ENTRADA":
        if not numero.strip() or validade is None:
            raise RegraNegocio("Informe o número do lote e a validade para este produto.")
        if validade < timezone.localdate():
            raise RegraNegocio("A mercadoria recebida já está vencida. Confira a validade.")
        lote, _ = LoteProduto.objects.get_or_create(produto=produto, numero=numero.strip(),
                                                   defaults={"validade": validade, "custo_unitario": custo})
        lote = LoteProduto.objects.select_for_update().get(pk=lote.pk)
        if lote.validade != validade:
            raise RegraNegocio("Este número de lote já tem outra validade cadastrada.")
        saldo_novo = lote.quantidade + quantidade
        lote.custo_unitario = ((lote.quantidade * lote.custo_unitario + quantidade * custo) / saldo_novo).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        delta = quantidade
    else:
        if lote is None or lote.produto_id != produto.pk:
            raise RegraNegocio("Selecione o lote que será ajustado.")
        lote = LoteProduto.objects.select_for_update().get(pk=lote.pk)
        delta = -quantidade if tipo == "PERDA" else quantidade - lote.quantidade
        if lote.quantidade + delta < ZERO:
            raise RegraNegocio("A perda informada supera o saldo do lote.")
    lote.quantidade += delta
    lote.save(update_fields=["quantidade", "custo_unitario"])
    return lote, delta
