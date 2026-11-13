from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Cliente, Fornecedor, MovimentoCaixa, Produto, Venda
from .services import EstoqueInsuficiente, abrir_caixa, ajustar_estoque, cancelar_venda, registrar_venda

D = Decimal


class BaseTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.gerente = User.objects.create_user("gerente", password="x12345678", is_staff=True)
        self.func = User.objects.create_user("func", password="x12345678")
        self.caixa = abrir_caixa(D("50"), self.func)
        self.fornecedor = Fornecedor.objects.create(nome="Distribuidora")
        self.racao = Produto.objects.create(nome="Ração 25kg", unidade="SC", preco_venda=D("100"),
                                            estoque_atual=D("10"), estoque_minimo=D("3"))

    def vender(self, qtd, forma="DINHEIRO", cliente=""):
        cadastro = Cliente.objects.get_or_create(nome=cliente)[0] if cliente else None
        return registrar_venda(Venda(forma_pagamento=forma, cliente=cliente, cliente_cadastro=cadastro),
                               [{"produto": self.racao, "quantidade": D(qtd), "preco_unitario": D("100")}], self.func)


class ServicosTest(BaseTest):
    def test_venda_baixa_estoque_e_calcula_total(self):
        v = self.vender("2.5")
        self.racao.refresh_from_db()
        self.assertEqual(self.racao.estoque_atual, D("7.5"))
        self.assertEqual(v.total, D("250.00"))
        self.assertEqual(v.itens.count(), 1)

    def test_estoque_insuficiente(self):
        with self.assertRaises(EstoqueInsuficiente):
            self.vender("11")
        self.racao.refresh_from_db()
        self.assertEqual(self.racao.estoque_atual, D("10"))
        self.assertEqual(Venda.objects.count(), 0)

    def test_cancelar_devolve_estoque(self):
        v = self.vender("4")
        cancelar_venda(v, self.gerente)
        self.racao.refresh_from_db()
        self.assertEqual(self.racao.estoque_atual, D("10"))
        self.assertTrue(Venda.objects.get(pk=v.pk).cancelada)
        cancelar_venda(v, self.gerente)  # idempotente
        self.racao.refresh_from_db()
        self.assertEqual(self.racao.estoque_atual, D("10"))

    def test_ajustes(self):
        ajustar_estoque(self.racao, "ENTRADA", D("5"), "", self.func, self.fornecedor, D("70"))
        ajustar_estoque(self.racao, "PERDA", D("2"), "", self.func)
        ajustar_estoque(self.racao, "AJUSTE", D("20"), "contagem", self.func)
        self.racao.refresh_from_db()
        self.assertEqual(self.racao.estoque_atual, D("20"))
        with self.assertRaises(EstoqueInsuficiente):
            ajustar_estoque(self.racao, "PERDA", D("99"), "", self.func)


class TelasTest(BaseTest):
    def test_login_obrigatorio(self):
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/entrar/", r.url)

    def test_paginas_principais(self):
        self.client.login(username="func", password="x12345678")
        for nome in ["dashboard", "produto_lista", "produto_novo", "categoria_lista", "venda_lista", "venda_nova",
                     "caixa", "movimento_novo"]:
            self.assertEqual(self.client.get(reverse(nome)).status_code, 200, nome)

    def test_fluxo_de_venda_pela_tela(self):
        self.client.login(username="func", password="x12345678")
        dados = {
            "data": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "forma_pagamento": "PIX", "cliente": "", "observacao": "",
            "itens-TOTAL_FORMS": "1", "itens-INITIAL_FORMS": "0", "itens-MIN_NUM_FORMS": "1", "itens-MAX_NUM_FORMS": "1000",
            "itens-0-produto": self.racao.pk, "itens-0-quantidade": "2", "itens-0-preco_unitario": "100.00",
        }
        r = self.client.post(reverse("venda_nova"), dados)
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        self.racao.refresh_from_db()
        self.assertEqual(self.racao.estoque_atual, D("8"))

    def test_venda_sem_itens_e_recusada(self):
        self.client.login(username="func", password="x12345678")
        dados = {"data": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "forma_pagamento": "PIX",
                 "itens-TOTAL_FORMS": "1", "itens-INITIAL_FORMS": "0", "itens-MIN_NUM_FORMS": "1", "itens-MAX_NUM_FORMS": "1000",
                 "itens-0-produto": "", "itens-0-quantidade": "", "itens-0-preco_unitario": ""}
        r = self.client.post(reverse("venda_nova"), dados)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Venda.objects.count(), 0)

    def test_fiado_exige_cliente(self):
        self.client.login(username="func", password="x12345678")
        dados = {"data": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "forma_pagamento": "FIADO", "cliente": "",
                 "itens-TOTAL_FORMS": "1", "itens-INITIAL_FORMS": "0", "itens-MIN_NUM_FORMS": "1", "itens-MAX_NUM_FORMS": "1000",
                 "itens-0-produto": self.racao.pk, "itens-0-quantidade": "1", "itens-0-preco_unitario": "100"}
        r = self.client.post(reverse("venda_nova"), dados)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Venda.objects.count(), 0)

    def test_cancelar_so_gerente(self):
        v = self.vender("1")
        self.client.login(username="func", password="x12345678")
        self.assertEqual(self.client.post(reverse("venda_cancelar", args=[v.pk])).status_code, 403)
        self.client.login(username="gerente", password="x12345678")
        self.assertEqual(self.client.post(reverse("venda_cancelar", args=[v.pk])).status_code, 302)

    def test_caixa_calcula_saldo_e_ignora_fiado_e_canceladas(self):
        self.vender("1")                      # 100 dinheiro
        self.vender("1", "FIADO", "João")     # 100 fiado (não entra no caixa)
        cancelada = self.vender("1", "PIX")   # cancelada (não conta)
        cancelar_venda(cancelada, self.gerente)
        MovimentoCaixa.objects.create(tipo="SAIDA", motivo="FORNECEDOR", descricao="Fornecedor", valor=D("30"))
        MovimentoCaixa.objects.create(tipo="ENTRADA", motivo="RECEBIMENTO", descricao="Fiado pago", valor=D("10"))
        self.client.login(username="func", password="x12345678")
        r = self.client.get(reverse("caixa"))
        resumo = r.context["r"]
        self.assertEqual(resumo["recebido"], D("100"))
        self.assertEqual(resumo["fiado"], D("100"))
        self.assertEqual(resumo["saldo"], D("80"))
