from copy import copy
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from .models import Cliente, MovimentoCaixa, Produto, Venda
from .services import (RegraNegocio, abrir_caixa, ajustar_estoque, cancelar_venda, corrigir_venda,
                       dinheiro_no_caixa, excluir_movimento, fechar_caixa, receber_fiado,
                       registrar_movimento, registrar_venda, vincular_recebimento_anterior)
from .tests import BaseTest

D = Decimal


class OperacaoTest(BaseTest):
    def itens(self, quantidade="1", preco="100", desconto="0", produto=None):
        return [{"produto": produto or self.racao, "quantidade": D(quantidade),
                 "preco_unitario": D(preco), "desconto": D(desconto)}]

    def test_descontos_e_pagamento_dividido(self):
        venda = registrar_venda(Venda(desconto=D("5")), self.itens("2", desconto="10"), self.func,
            [{"forma": "DINHEIRO", "valor": D("85")}, {"forma": "PIX", "valor": D("100")}])
        self.assertEqual(venda.total, D("185"))
        self.assertEqual(venda.itens.get().subtotal, D("190"))
        self.assertEqual(venda.forma_pagamento, "DIVIDIDO")
        self.assertEqual(dinheiro_no_caixa(self.caixa), D("135"))

    def test_pagamento_dividido_incompleto_nao_mexe_no_estoque(self):
        with self.assertRaises(RegraNegocio):
            registrar_venda(Venda(), self.itens(), self.func, [{"forma": "PIX", "valor": D("99.99")}])
        self.racao.refresh_from_db()
        self.assertEqual(self.racao.estoque_atual, D("10"))
        self.assertFalse(Venda.objects.exists())

    def test_desconto_excessivo_e_quantidade_negativa_recusados(self):
        for itens, venda in [(self.itens(desconto="101"), Venda()), (self.itens("-1"), Venda()),
                             (self.itens(), Venda(desconto=D("101")))]:
            with self.assertRaises(RegraNegocio):
                registrar_venda(venda, itens, self.func)
        self.assertFalse(Venda.objects.exists())

    def test_arredondamento_meio_centavo(self):
        venda = registrar_venda(Venda(), self.itens("0.001", "5"), self.func)
        self.assertEqual(venda.total, D("0.01"))
        self.assertEqual(venda.itens.get().subtotal, D("0.01"))

    def test_recebimento_parcial_baixa_mais_antiga_e_total_quita(self):
        primeira = self.vender("1", "FIADO", "Ana")
        segunda = self.vender("2", "FIADO", "Ana")
        cliente = primeira.cliente_cadastro
        movimento = receber_fiado(cliente, D("150"), "PIX", self.func)
        self.assertEqual(primeira.saldo_fiado, D("0"))
        self.assertEqual(segunda.saldo_fiado, D("150"))
        self.assertEqual(cliente.saldo_devedor, D("150"))
        self.assertEqual(movimento.baixas_fiado.count(), 2)
        self.assertEqual(dinheiro_no_caixa(self.caixa), D("50"))
        receber_fiado(cliente, D("150"), "DINHEIRO", self.func)
        self.assertEqual(cliente.saldo_devedor, D("0"))
        self.assertEqual(dinheiro_no_caixa(self.caixa), D("200"))

    def test_nao_recebe_acima_da_divida_nem_exclui_baixa(self):
        venda = self.vender("1", "FIADO", "Ana")
        with self.assertRaises(RegraNegocio):
            receber_fiado(venda.cliente_cadastro, D("101"), "DINHEIRO", self.func)
        self.assertFalse(MovimentoCaixa.objects.exists())
        movimento = receber_fiado(venda.cliente_cadastro, D("20"), "DINHEIRO", self.func)
        with self.assertRaises(RegraNegocio):
            excluir_movimento(movimento, self.gerente)
        with self.assertRaises(RegraNegocio):
            cancelar_venda(venda, self.gerente)
        self.assertEqual(venda.cliente_cadastro.saldo_devedor, D("80"))

    def test_recebimento_antigo_e_conciliado_sem_duplicar_dinheiro(self):
        venda = self.vender("1", "FIADO", "Ana")
        movimento = MovimentoCaixa.objects.create(tipo="ENTRADA", motivo="RECEBIMENTO", descricao="Fiado pago", valor=D("30"))
        vincular_recebimento_anterior(venda.cliente_cadastro, movimento, self.gerente)
        self.assertEqual(venda.cliente_cadastro.saldo_devedor, D("70"))
        self.assertEqual(MovimentoCaixa.objects.count(), 1)
        with self.assertRaises(RegraNegocio):
            vincular_recebimento_anterior(venda.cliente_cadastro, movimento, self.gerente)

    def test_fiado_dividido_precisa_cliente_e_so_registra_parte_a_prazo(self):
        parcelas = [{"forma": "PIX", "valor": D("40")}, {"forma": "FIADO", "valor": D("60")}]
        with self.assertRaises(RegraNegocio):
            registrar_venda(Venda(), self.itens(), self.func, parcelas)
        cliente = Cliente.objects.create(nome="Ana")
        venda = registrar_venda(Venda(cliente_cadastro=cliente), self.itens(), self.func, parcelas)
        self.assertEqual(cliente.saldo_devedor, D("60"))
        cancelar_venda(venda, self.gerente)
        self.assertEqual(cliente.saldo_devedor, D("0"))

    def test_entrada_vincula_fornecedor_e_atualiza_custo(self):
        ajustar_estoque(self.racao, "ENTRADA", D("3"), "Compra NF 10", self.gerente, self.fornecedor, D("65.50"))
        self.racao.refresh_from_db()
        self.assertEqual(self.racao.preco_custo, D("65.50"))
        self.assertEqual(self.racao.estoque_atual, D("13"))
        self.assertEqual(self.racao.movimentos.get().fornecedor, self.fornecedor)
        with self.assertRaises(RegraNegocio):
            ajustar_estoque(self.racao, "ENTRADA", D("1"), "", self.gerente)

    def test_fechamento_separa_pix_cartao_e_dinheiro_e_preserva_historico(self):
        venda = self.vender("1")
        self.vender("1", "PIX")
        self.vender("1", "DEBITO")
        registrar_movimento(MovimentoCaixa(tipo="SAIDA", valor=D("20"), descricao="Despesa"), self.func)
        caixa = fechar_caixa(self.caixa, D("125"), self.func)
        self.assertEqual(caixa.dinheiro_esperado, D("130"))
        self.assertEqual(caixa.diferenca, D("-5"))
        with self.assertRaises(RegraNegocio):
            cancelar_venda(venda, self.gerente)
        with self.assertRaises(RegraNegocio):
            self.vender("1")
        with self.assertRaises(RegraNegocio):
            fechar_caixa(caixa, D("130"), self.func)
        novo = abrir_caixa(D("25"), self.func)
        self.assertEqual(dinheiro_no_caixa(novo), D("25"))

    def test_nao_abre_dois_caixas_e_outro_funcionario_nao_fecha(self):
        with self.assertRaises(RegraNegocio):
            abrir_caixa(D("0"), self.func)
        terceiro = type(self.func).objects.create_user("outro")
        with self.assertRaises(RegraNegocio):
            fechar_caixa(self.caixa, D("50"), terceiro)

    def test_correcao_aplica_delta_e_guarda_versao_anterior(self):
        venda = self.vender("2")
        alterada = copy(venda)
        alterada.desconto = D("10")
        nova = corrigir_venda(alterada, self.itens("3"), self.gerente, motivo="Quantidade correta", versao=1)
        self.racao.refresh_from_db()
        self.assertEqual(self.racao.estoque_atual, D("7"))
        self.assertEqual(nova.total, D("290"))
        self.assertEqual(nova.versao, 2)
        self.assertEqual(nova.alteracoes.get().anterior["total"], "200.00")
        self.assertEqual(nova.criado_por, self.func)
        with self.assertRaises(RegraNegocio):
            corrigir_venda(alterada, self.itens(), self.gerente, motivo="Tela antiga", versao=1)

    def test_correcao_com_estoque_insuficiente_reverte_tudo(self):
        venda = self.vender("2")
        with self.assertRaises(RegraNegocio):
            corrigir_venda(venda, self.itens("11"), self.gerente, motivo="Tentativa", versao=1)
        self.racao.refresh_from_db()
        venda.refresh_from_db()
        self.assertEqual(self.racao.estoque_atual, D("8"))
        self.assertEqual(venda.total, D("200"))
        self.assertFalse(venda.alteracoes.exists())

    def test_correcao_nao_reduz_fiado_abaixo_do_que_ja_foi_pago(self):
        venda = self.vender("2", "FIADO", "Ana")
        receber_fiado(venda.cliente_cadastro, D("150"), "PIX", self.func)
        with self.assertRaises(RegraNegocio):
            corrigir_venda(venda, self.itens("1"), self.gerente, motivo="Menor", versao=1)
        corrigir_venda(venda, self.itens("3"), self.gerente, motivo="Maior", versao=1)
        self.assertEqual(venda.cliente_cadastro.saldo_devedor, D("150"))


class OperacaoTelasTest(BaseTest):
    def test_telas_novas_e_comprovante(self):
        venda = self.vender("1", "FIADO", "Ana")
        self.client.force_login(self.gerente)
        telas = [("cliente_lista", []), ("cliente_novo", []), ("cliente_detalhe", [venda.cliente_cadastro_id]),
                 ("cliente_editar", [venda.cliente_cadastro_id]), ("fornecedor_lista", []), ("fornecedor_novo", []),
                 ("fornecedor_detalhe", [self.fornecedor.pk]), ("fornecedor_editar", [self.fornecedor.pk]),
                 ("caixa_abrir", []), ("caixa_fechar", [self.caixa.pk]), ("venda_editar", [venda.pk]),
                 ("venda_comprovante", [venda.pk])]
        for nome, args in telas:
            with self.subTest(tela=nome):
                response = self.client.get(reverse(nome, args=args))
                self.assertEqual(response.status_code, 200)
        self.assertContains(self.client.get(reverse("venda_comprovante", args=[venda.pk])), "Não é documento fiscal")

    def test_correcao_pela_tela_com_formset(self):
        venda = self.vender("2")
        self.client.force_login(self.gerente)
        response = self.client.post(reverse("venda_editar", args=[venda.pk]), {
            "data": timezone.localtime(venda.data).strftime("%Y-%m-%dT%H:%M"), "forma_pagamento": "PIX", "desconto": "5",
            "versao": "1", "motivo_correcao": "Ajuste do pedido", "itens-TOTAL_FORMS": "1",
            "itens-INITIAL_FORMS": "1", "itens-0-id": str(venda.itens.get().pk), "itens-0-venda": venda.pk,
            "itens-0-produto": self.racao.pk, "itens-0-quantidade": "3", "itens-0-preco_unitario": "100",
        })
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        venda.refresh_from_db()
        self.assertEqual(venda.total, D("295"))

    def test_funcionario_nao_corrige_venda(self):
        venda = self.vender("1")
        self.client.force_login(self.func)
        self.assertEqual(self.client.get(reverse("venda_editar", args=[venda.pk])).status_code, 403)
