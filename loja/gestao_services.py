from decimal import Decimal

from django.db import transaction

from .auditoria import com_usuario
from .models import ContaPagar, LoteProduto, MovimentoCaixa, MovimentoEstoque, PagamentoConta, Produto
from .permissoes import cargo_usuario
from .services import RegraNegocio, caixa_aberto, decimal_valido, registrar_movimento


@transaction.atomic
@com_usuario
def salvar_produto(form, usuario):
    if cargo_usuario(usuario) not in ("GERENTE", "ESTOQUISTA"):
        raise RegraNegocio("Seu perfil não permite alterar produtos.")
    produto = form.save(commit=False)
    novo = produto.pk is None
    if not novo:
        anterior = Produto.objects.select_for_update().get(pk=produto.pk)
        produto.estoque_atual = anterior.estoque_atual
        if anterior.controla_lote and not produto.controla_lote and anterior.lotes.exists():
            raise RegraNegocio("O controle de lote não pode ser desativado em um produto com histórico de lotes.")
    produto.save()
    lote = None
    if produto.controla_lote and produto.estoque_atual and not produto.lotes.exists():
        lote = LoteProduto.objects.create(produto=produto, numero="SALDO-INICIAL", quantidade=produto.estoque_atual,
                                          custo_unitario=produto.preco_custo)
    if novo and produto.estoque_atual:
        MovimentoEstoque.objects.create(produto=produto, quantidade=produto.estoque_atual, motivo="AJUSTE",
                                        observacao="Estoque inicial", usuario=usuario, lote=lote)
    return produto


@transaction.atomic
@com_usuario
def salvar_conta(form, usuario):
    if cargo_usuario(usuario) != "GERENTE":
        raise RegraNegocio("Somente um gerente pode alterar contas a pagar.")
    conta = form.save(commit=False)
    if conta.pk:
        atual = ContaPagar.objects.select_for_update().get(pk=conta.pk)
        if conta.valor < atual.valor - atual.saldo:
            raise RegraNegocio("O total não pode ser menor que os pagamentos já registrados.")
        conta.criado_por = atual.criado_por
    else:
        conta.criado_por = usuario
    conta.save()
    return conta


@transaction.atomic
@com_usuario
def pagar_conta(conta, valor, forma, usuario):
    if cargo_usuario(usuario) != "GERENTE":
        raise RegraNegocio("Somente um gerente pode pagar contas.")
    caixa_aberto()
    conta = ContaPagar.objects.select_for_update().get(pk=conta.pk)
    valor = decimal_valido(valor, minimo=Decimal("0.01"))
    if valor > conta.saldo:
        raise RegraNegocio("O pagamento supera o saldo desta conta.")
    movimento = registrar_movimento(MovimentoCaixa(tipo="SAIDA", valor=valor, forma=forma,
        motivo="FORNECEDOR" if conta.fornecedor_id else "DESPESA", descricao=f"Conta #{conta.pk}: {conta.descricao}"[:200]), usuario)
    return PagamentoConta.objects.create(conta=conta, movimento=movimento, valor=valor)
