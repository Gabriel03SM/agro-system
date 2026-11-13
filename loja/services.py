"""Operações de estoque e caixa, sempre dentro de uma transação."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from .auditoria import com_usuario
from .lotes import ajustar_lote, consumir, devolver
from .permissoes import cargo_usuario
from .models import (AlteracaoVenda, Cliente, ItemVenda, MovimentoCaixa, MovimentoEstoque,
                     PagamentoVenda, Produto, RecebimentoFiado, SessaoCaixa, Venda)

ZERO = Decimal("0")
CENTAVO = Decimal("0.01")
FORMAS = {codigo for codigo, _ in Venda.FORMAS if codigo != "DIVIDIDO"}


class RegraNegocio(Exception):
    pass


class EstoqueInsuficiente(RegraNegocio):
    pass


def fmt_qtd(valor):
    return format(Decimal(valor).normalize(), "f")


def decimal_valido(valor, casas=2, minimo=ZERO, nome="Valor", maximo=Decimal("9999999999.99")):
    try:
        numero = Decimal(str(valor))
        if not numero.is_finite() or numero < minimo or numero > maximo:
            raise ValueError
        if numero != numero.quantize(Decimal(10) ** -casas):
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        raise RegraNegocio(f"{nome} inválido.") from None
    return numero


def _travar(ids):
    return {p.pk: p for p in Produto.objects.select_for_update().filter(pk__in=ids).order_by("pk")}


def caixa_aberto():
    caixa = SessaoCaixa.objects.select_for_update().filter(aberto=True).first()
    if caixa is None:
        raise RegraNegocio("Abra o caixa antes de registrar vendas ou movimentações financeiras.")
    return caixa


def _validar_data(data, caixa):
    if timezone.is_naive(data) or data < caixa.aberto_em.replace(second=0, microsecond=0):
        raise RegraNegocio("A data deve pertencer ao caixa aberto. Não é possível lançar em um caixa anterior.")
    if data > timezone.now() + timedelta(minutes=1):
        raise RegraNegocio("Não é possível registrar uma data futura.")


@transaction.atomic
@com_usuario
def abrir_caixa(troco, usuario):
    if cargo_usuario(usuario) not in ("GERENTE", "CAIXA"):
        raise RegraNegocio("Seu perfil não permite operações financeiras.")
    troco = decimal_valido(troco, nome="Troco inicial")
    if SessaoCaixa.objects.filter(aberto=True).exists():
        raise RegraNegocio("Já existe um caixa aberto. Feche-o antes de abrir outro.")
    try:
        with transaction.atomic():
            return SessaoCaixa.objects.create(troco_inicial=troco, aberto_por=usuario)
    except IntegrityError:
        raise RegraNegocio("Outro usuário já abriu o caixa. Atualize a página.") from None


def dinheiro_no_caixa(caixa):
    vendas = PagamentoVenda.objects.filter(venda__caixa=caixa, venda__cancelada=False,
                                           forma="DINHEIRO").aggregate(t=Sum("valor"))["t"] or ZERO
    movimentos = caixa.movimentos.filter(forma="DINHEIRO")
    entradas = movimentos.filter(tipo="ENTRADA").aggregate(t=Sum("valor"))["t"] or ZERO
    saidas = movimentos.filter(tipo="SAIDA").aggregate(t=Sum("valor"))["t"] or ZERO
    return caixa.troco_inicial + vendas + entradas - saidas


@transaction.atomic
@com_usuario
def fechar_caixa(caixa, contado, usuario, observacao=""):
    caixa = SessaoCaixa.objects.select_for_update().get(pk=caixa.pk)
    if not caixa.aberto:
        raise RegraNegocio("Este caixa já foi fechado.")
    if usuario.pk != caixa.aberto_por_id and cargo_usuario(usuario) != "GERENTE":
        raise RegraNegocio("Somente quem abriu o caixa ou um gerente pode fechá-lo.")
    caixa.dinheiro_contado = decimal_valido(contado, nome="Dinheiro contado")
    caixa.dinheiro_esperado = dinheiro_no_caixa(caixa)
    caixa.fechado_em = timezone.now()
    caixa.fechado_por = usuario
    caixa.observacao = observacao
    caixa.aberto = False
    caixa.save()
    return caixa


def _cliente(venda):
    if venda.cliente_cadastro_id:
        cliente = Cliente.objects.select_for_update().get(pk=venda.cliente_cadastro_id)
        if not cliente.ativo:
            raise RegraNegocio("Este cliente está inativo. Ative o cadastro antes de usá-lo na venda.")
        venda.cliente = cliente.nome


def _itens(itens):
    if not itens:
        raise RegraNegocio("Adicione pelo menos um item à venda.")
    resultado, quantidades, total = [], defaultdict(Decimal), ZERO
    for item in itens:
        qtd = decimal_valido(item["quantidade"], 3, Decimal("0.001"), "Quantidade", Decimal("999999999.999"))
        preco = decimal_valido(item["preco_unitario"], nome="Preço unitário", maximo=Decimal("99999999.99"))
        desconto = decimal_valido(item.get("desconto") or ZERO, nome="Desconto do item")
        bruto = (qtd * preco).quantize(CENTAVO, rounding=ROUND_HALF_UP)
        if desconto > bruto:
            raise RegraNegocio("O desconto do item não pode superar seu valor.")
        quantidades[item["produto"].pk] += qtd
        total += bruto - desconto
        resultado.append({"produto": item["produto"], "quantidade": qtd, "preco_unitario": preco, "desconto": desconto})
    return resultado, quantidades, total


def _pagamentos(venda, total, pagamentos):
    desconto = decimal_valido(venda.desconto, nome="Desconto da venda")
    if desconto > total:
        raise RegraNegocio("O desconto da venda não pode superar o subtotal dos itens.")
    venda.total = decimal_valido(total - desconto, nome="Total da venda")
    if pagamentos is None:
        if venda.forma_pagamento not in FORMAS:
            raise RegraNegocio("Informe os valores de cada forma no pagamento dividido.")
        pagamentos = [{"forma": venda.forma_pagamento, "valor": venda.total}]
    parcelas = defaultdict(Decimal)
    for pagamento in pagamentos:
        forma = pagamento["forma"]
        if forma not in FORMAS:
            raise RegraNegocio("Forma de pagamento inválida.")
        parcelas[forma] += decimal_valido(pagamento["valor"], nome="Pagamento")
    parcelas = {forma: valor for forma, valor in parcelas.items() if valor > ZERO}
    if not parcelas and venda.total == ZERO:
        parcelas = {"DINHEIRO": ZERO}
    if sum(parcelas.values(), ZERO) != venda.total:
        raise RegraNegocio(f"A soma dos pagamentos deve ser igual ao total de R$ {venda.total:.2f}.")
    if parcelas.get("FIADO", ZERO) and not venda.cliente_cadastro_id:
        raise RegraNegocio("Selecione um cliente cadastrado para vender fiado.")
    venda.forma_pagamento = next(iter(parcelas)) if len(parcelas) == 1 else "DIVIDIDO"
    return parcelas


def _gravar_itens(venda, itens, produtos, parcelas, custos=None):
    for item in itens:
        produto = produtos[item["produto"].pk]
        item_salvo = ItemVenda.objects.create(venda=venda, produto=produto, quantidade=item["quantidade"],
                                 preco_unitario=item["preco_unitario"], desconto=item["desconto"],
                                 preco_custo=(custos or {}).get(produto.pk, produto.preco_custo))
        consumir(item_salvo)
    for forma, valor in parcelas.items():
        PagamentoVenda.objects.create(venda=venda, forma=forma, valor=valor)


@transaction.atomic
@com_usuario
def registrar_venda(venda, itens, usuario, pagamentos=None):
    if cargo_usuario(usuario) not in ("GERENTE", "CAIXA"):
        raise RegraNegocio("Seu perfil não permite operações financeiras.")
    if venda.pk:
        raise RegraNegocio("Use a correção para alterar uma venda existente.")
    venda.caixa = caixa_aberto()
    _validar_data(venda.data, venda.caixa)
    _cliente(venda)
    itens, necessario, total = _itens(itens)
    parcelas = _pagamentos(venda, total, pagamentos)
    produtos = _travar(necessario)
    for pk, qtd in necessario.items():
        produto = produtos.get(pk)
        if produto is None or not produto.ativo:
            raise RegraNegocio("Um dos produtos está inativo ou não existe mais.")
        if produto.estoque_atual < qtd:
            raise EstoqueInsuficiente(f"Estoque insuficiente de “{produto.nome}”: disponível "
                                      f"{fmt_qtd(produto.estoque_atual)}, pedido {fmt_qtd(qtd)}.")
    venda.criado_por = usuario
    venda.save()
    _gravar_itens(venda, itens, produtos, parcelas)
    for pk, qtd in necessario.items():
        produto = produtos[pk]
        produto.estoque_atual -= qtd
        produto.save(update_fields=["estoque_atual"])
        MovimentoEstoque.objects.create(produto=produto, quantidade=-qtd, motivo="VENDA", venda=venda, usuario=usuario)
    return venda


def _travar_venda(venda, novo_cliente_id=None):
    atual = Venda.objects.get(pk=venda.pk)
    if atual.caixa_id:
        caixa = SessaoCaixa.objects.select_for_update().get(pk=atual.caixa_id)
        if not caixa.aberto:
            raise RegraNegocio("O caixa desta venda já foi fechado. Seus lançamentos não podem ser alterados.")
    ids = {pk for pk in (atual.cliente_cadastro_id, novo_cliente_id) if pk}
    list(Cliente.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    return Venda.objects.select_for_update().get(pk=venda.pk)


@transaction.atomic
@com_usuario
def corrigir_venda(venda, itens, usuario, pagamentos=None, motivo="", versao=None):
    if cargo_usuario(usuario) != "GERENTE":
        raise RegraNegocio("Somente um gerente pode corrigir vendas.")
    if not motivo.strip():
        raise RegraNegocio("Informe o motivo da correção.")
    atual = _travar_venda(venda, venda.cliente_cadastro_id)
    if atual.cancelada:
        raise RegraNegocio("Uma venda cancelada não pode ser corrigida.")
    if versao != atual.versao:
        raise RegraNegocio("Esta venda foi alterada por outro usuário. Reabra a tela antes de corrigir.")
    if atual.caixa_id:
        _validar_data(venda.data, atual.caixa)
    _cliente(venda)
    itens, necessario, total = _itens(itens)
    parcelas = _pagamentos(venda, total, pagamentos)
    recebido = atual.recebimentos.aggregate(t=Sum("valor"))["t"] or ZERO
    if recebido and (venda.cliente_cadastro_id != atual.cliente_cadastro_id or parcelas.get("FIADO", ZERO) < recebido):
        raise RegraNegocio("Esta venda já tem recebimentos. Mantenha o cliente e um valor fiado igual ou maior ao recebido.")
    anteriores, custos, snapshot_itens = defaultdict(Decimal), {}, []
    for item in atual.itens.all():
        anteriores[item.produto_id] += item.quantidade
        custos[item.produto_id] = item.preco_custo
        snapshot_itens.append({"produto": item.produto_id, "quantidade": str(item.quantidade),
                               "preco_unitario": str(item.preco_unitario), "desconto": str(item.desconto)})
    produtos = _travar(set(anteriores) | set(necessario))
    for pk, qtd in necessario.items():
        produto = produtos.get(pk)
        if produto is None or (not produto.ativo and pk not in anteriores):
            raise RegraNegocio("Um dos produtos está inativo ou não existe mais.")
        if produto.estoque_atual + anteriores[pk] < qtd:
            raise EstoqueInsuficiente(f"Estoque insuficiente de “{produto.nome}” para a correção.")
    AlteracaoVenda.objects.create(venda=atual, usuario=usuario, motivo=motivo.strip(), anterior={
        "data": atual.data.isoformat(), "cliente": atual.cliente, "cliente_cadastro": atual.cliente_cadastro_id,
        "desconto": str(atual.desconto), "total": str(atual.total), "observacao": atual.observacao,
        "versao": atual.versao, "itens": snapshot_itens,
        "pagamentos": [{"forma": p.forma, "valor": str(p.valor)} for p in atual.pagamentos.all()],
    })
    for campo in ("data", "cliente", "cliente_cadastro_id", "observacao", "desconto", "total", "forma_pagamento"):
        setattr(atual, campo, getattr(venda, campo))
    atual.versao += 1
    atual.save()
    devolver(atual)
    atual.itens.all().delete()
    atual.pagamentos.all().delete()
    _gravar_itens(atual, itens, produtos, parcelas, custos)
    for pk in sorted(produtos):
        delta = anteriores[pk] - necessario[pk]
        if delta:
            produto = produtos[pk]
            produto.estoque_atual += delta
            produto.save(update_fields=["estoque_atual"])
            MovimentoEstoque.objects.create(produto=produto, quantidade=delta, motivo="CORRECAO", venda=atual,
                                            usuario=usuario, observacao=motivo.strip())
    return atual


@transaction.atomic
@com_usuario
def cancelar_venda(venda, usuario):
    if cargo_usuario(usuario) != "GERENTE":
        raise RegraNegocio("Somente um gerente pode cancelar vendas.")
    if Venda.objects.get(pk=venda.pk).cancelada:
        return Venda.objects.get(pk=venda.pk)
    venda = _travar_venda(venda)
    if venda.cancelada:
        return venda
    if venda.recebimentos.exists():
        raise RegraNegocio("Esta venda tem recebimentos de fiado. Não é possível cancelá-la sem tratar os valores recebidos.")
    soma = defaultdict(Decimal)
    for item in venda.itens.all():
        soma[item.produto_id] += item.quantidade
    produtos = _travar(soma)
    devolver(venda)
    for pk, qtd in soma.items():
        produto = produtos[pk]
        produto.estoque_atual += qtd
        produto.save(update_fields=["estoque_atual"])
        MovimentoEstoque.objects.create(produto=produto, quantidade=qtd, motivo="CANCELAMENTO", venda=venda, usuario=usuario)
    venda.cancelada = True
    venda.cancelada_em = timezone.now()
    venda.versao += 1
    venda.save(update_fields=["cancelada", "cancelada_em", "versao"])
    return venda


@transaction.atomic
@com_usuario
def ajustar_estoque(produto, tipo, quantidade, observacao, usuario, fornecedor=None, custo_unitario=None,
                     lote=None, numero_lote="", validade=None):
    if cargo_usuario(usuario) not in ("GERENTE", "ESTOQUISTA"):
        raise RegraNegocio("Seu perfil não permite alterar o estoque.")
    quantidade = decimal_valido(quantidade, 3, nome="Quantidade", maximo=Decimal("999999999.999"))
    if tipo not in ("ENTRADA", "PERDA", "AJUSTE"):
        raise RegraNegocio("Tipo de ajuste inválido.")
    if tipo in ("ENTRADA", "PERDA") and quantidade <= ZERO:
        raise RegraNegocio("Informe uma quantidade maior que zero.")
    p = Produto.objects.select_for_update().get(pk=produto.pk)
    if tipo == "ENTRADA":
        if fornecedor is None or not fornecedor.ativo or custo_unitario is None:
            raise RegraNegocio("Informe um fornecedor ativo e o custo unitário da entrada.")
        p.preco_custo = decimal_valido(custo_unitario, nome="Custo unitário", maximo=Decimal("99999999.99"))
        delta = quantidade
    elif tipo == "PERDA":
        if p.estoque_atual < quantidade:
            raise EstoqueInsuficiente(f"Estoque atual ({fmt_qtd(p.estoque_atual)}) é menor que a perda informada.")
        delta = -quantidade
    else:
        delta = quantidade - p.estoque_atual
    lote_movimento = None
    if p.controla_lote:
        lote_movimento, delta = ajustar_lote(p, tipo, quantidade, p.preco_custo, lote, numero_lote, validade)
    if delta == ZERO:
        return p
    p.estoque_atual = decimal_valido(p.estoque_atual + delta, 3, nome="Estoque", maximo=Decimal("999999999.999"))
    p.save(update_fields=["estoque_atual", "preco_custo"])
    MovimentoEstoque.objects.create(produto=p, quantidade=delta, motivo=tipo, observacao=observacao, usuario=usuario,
                                    fornecedor=fornecedor if tipo == "ENTRADA" else None,
                                    custo_unitario=p.preco_custo if tipo == "ENTRADA" else None, lote=lote_movimento)
    return p


@transaction.atomic
@com_usuario
def registrar_movimento(movimento, usuario):
    if cargo_usuario(usuario) not in ("GERENTE", "CAIXA"):
        raise RegraNegocio("Seu perfil não permite operações financeiras.")
    movimento.caixa = caixa_aberto()
    _validar_data(movimento.data, movimento.caixa)
    if movimento.forma not in FORMAS - {"FIADO"} or movimento.tipo not in ("ENTRADA", "SAIDA"):
        raise RegraNegocio("Forma de pagamento ou tipo de movimento inválido.")
    if movimento.motivo == "RECEBIMENTO":
        raise RegraNegocio("Receba o fiado pela ficha do cliente para baixar a dívida corretamente.")
    movimento.valor = decimal_valido(movimento.valor, minimo=CENTAVO)
    movimento.criado_por = usuario
    movimento.save()
    return movimento


@transaction.atomic
@com_usuario
def excluir_movimento(movimento, usuario):
    if cargo_usuario(usuario) != "GERENTE":
        raise RegraNegocio("Somente um gerente pode excluir lançamentos.")
    if movimento.caixa_id:
        caixa = SessaoCaixa.objects.select_for_update().get(pk=movimento.caixa_id)
        if not caixa.aberto:
            raise RegraNegocio("Este lançamento pertence a um caixa fechado.")
    movimento = MovimentoCaixa.objects.select_for_update().get(pk=movimento.pk)
    if movimento.baixas_fiado.exists() or hasattr(movimento, "pagamento_conta"):
        raise RegraNegocio("Este lançamento está vinculado a um recebimento ou pagamento e não pode ser excluído avulsamente.")
    movimento.delete()


@transaction.atomic
@com_usuario
def receber_fiado(cliente, valor, forma, usuario):
    if cargo_usuario(usuario) not in ("GERENTE", "CAIXA"):
        raise RegraNegocio("Seu perfil não permite operações financeiras.")
    caixa = caixa_aberto()
    cliente = Cliente.objects.select_for_update().get(pk=cliente.pk)
    valor = decimal_valido(valor, minimo=CENTAVO, nome="Recebimento")
    if forma not in FORMAS - {"FIADO"}:
        raise RegraNegocio("Escolha uma forma de recebimento à vista.")
    vendas = list(Venda.objects.select_for_update().filter(cliente_cadastro=cliente, cancelada=False,
                                                          pagamentos__forma="FIADO").order_by("data", "pk"))
    saldos = [(venda, venda.saldo_fiado) for venda in vendas]
    if valor > sum((saldo for _, saldo in saldos), ZERO):
        raise RegraNegocio("O pagamento não pode superar o saldo devedor do cliente.")
    movimento = MovimentoCaixa.objects.create(tipo="ENTRADA", motivo="RECEBIMENTO", forma=forma, valor=valor,
        descricao=f"Recebimento de fiado: {cliente.nome}", criado_por=usuario, caixa=caixa)
    restante = valor
    for venda, saldo in saldos:
        parcela = min(restante, saldo)
        if parcela > ZERO:
            RecebimentoFiado.objects.create(venda=venda, movimento=movimento, valor=parcela)
            restante -= parcela
        if restante == ZERO:
            break
    return movimento


@transaction.atomic
@com_usuario
def vincular_recebimento_anterior(cliente, movimento, usuario):
    """Reconcilia uma entrada antiga sem lançar o dinheiro novamente no caixa."""
    if cargo_usuario(usuario) != "GERENTE":
        raise RegraNegocio("Somente um gerente pode vincular recebimentos anteriores.")
    cliente = Cliente.objects.select_for_update().get(pk=cliente.pk)
    movimento = MovimentoCaixa.objects.select_for_update().get(pk=movimento.pk)
    if (movimento.caixa_id or movimento.tipo != "ENTRADA" or movimento.motivo != "RECEBIMENTO"
            or movimento.baixas_fiado.exists()):
        raise RegraNegocio("Este recebimento não está disponível para conciliação.")
    vendas = list(Venda.objects.select_for_update().filter(cliente_cadastro=cliente, cancelada=False,
                                                          pagamentos__forma="FIADO").order_by("data", "pk"))
    saldos = [(venda, venda.saldo_fiado) for venda in vendas]
    if movimento.valor > sum((saldo for _, saldo in saldos), ZERO):
        raise RegraNegocio("O recebimento anterior supera a dívida deste cliente. Confira o lançamento e o cliente.")
    restante = movimento.valor
    for venda, saldo in saldos:
        valor = min(restante, saldo)
        if valor > ZERO:
            RecebimentoFiado.objects.create(venda=venda, movimento=movimento, valor=valor)
            restante -= valor
        if restante == ZERO:
            break
    return movimento
