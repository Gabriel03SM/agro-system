from datetime import timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from .csv_produtos import confirmar_importacao, preparar_importacao
from .forms import ContaPagarForm, ProdutoForm
from .gestao_services import pagar_conta, salvar_conta, salvar_produto
from .models import ContaPagar, LoteProduto, MovimentoCaixa, PerfilUsuario, Produto, RegistroAuditoria, Venda
from .relatorios import celula_csv, dados_relatorio, exportar_csv
from .services import RegraNegocio, ajustar_estoque, cancelar_venda, corrigir_venda, excluir_movimento, registrar_venda
from .tests import BaseTest
from .views import limites

D = Decimal


class LotesTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.vacina = Produto.objects.create(nome="Vacina", preco_venda=D("50"), controla_lote=True)

    def entrada(self, numero, dias, quantidade="5", custo="20"):
        return ajustar_estoque(self.vacina, "ENTRADA", D(quantidade), "Compra", self.gerente, self.fornecedor,
                               D(custo), numero_lote=numero, validade=timezone.localdate() + timedelta(days=dias))

    def vender_vacina(self, qtd="3"):
        return registrar_venda(Venda(), [{"produto": self.vacina, "quantidade": D(qtd), "preco_unitario": D("50")}], self.func)

    def test_baixa_prioriza_validade_e_cancelamento_devolve_lotes(self):
        self.entrada("depois", 60)
        self.entrada("antes", 10, "2", "15")
        venda = self.vender_vacina("3")
        self.assertEqual(self.vacina.lotes.get(numero="antes").quantidade, D("0"))
        self.assertEqual(self.vacina.lotes.get(numero="depois").quantidade, D("4"))
        consumos = venda.itens.get().consumos_lote.all()
        self.assertEqual(sum((c.quantidade * c.custo_unitario for c in consumos), D("0")), D("50"))
        cancelar_venda(venda, self.gerente)
        self.assertEqual(self.vacina.lotes.get(numero="antes").quantidade, D("2"))
        self.vacina.refresh_from_db()
        self.assertEqual(self.vacina.estoque_atual, D("7"))

    def test_vencido_nao_e_vendido_e_falha_reverte_tudo(self):
        self.entrada("antigo", 1)
        self.vacina.lotes.filter(numero="antigo").update(validade=timezone.localdate() - timedelta(days=1))
        with self.assertRaises(RegraNegocio):
            self.vender_vacina()
        self.assertFalse(Venda.objects.exists())
        self.assertEqual(self.vacina.lotes.get().quantidade, D("5"))
        with self.assertRaises(RegraNegocio):
            self.entrada("ja-vencido", -1)

    def test_correcao_recompoe_lotes_sem_duplicar_saldo(self):
        self.entrada("A", 30)
        venda = self.vender_vacina("3")
        corrigir_venda(venda, [{"produto": self.vacina, "quantidade": D("1"), "preco_unitario": D("50")}],
                       self.gerente, motivo="Uma unidade", versao=1)
        self.vacina.refresh_from_db()
        self.assertEqual(self.vacina.estoque_atual, D("4"))
        self.assertEqual(self.vacina.lotes.get().quantidade, D("4"))

    def test_perda_e_contagem_sao_do_lote_selecionado(self):
        self.entrada("A", 30)
        self.entrada("B", 60)
        lote = self.vacina.lotes.get(numero="A")
        ajustar_estoque(self.vacina, "AJUSTE", D("2"), "Contagem A", self.gerente, lote=lote)
        self.vacina.refresh_from_db()
        self.assertEqual(self.vacina.estoque_atual, D("7"))
        with self.assertRaises(RegraNegocio):
            ajustar_estoque(self.vacina, "PERDA", D("3"), "", self.gerente, lote=lote)

    def test_ativar_lote_preserva_estoque_anterior(self):
        dados = {"nome": self.racao.nome, "unidade": "SC", "preco_custo": "70", "preco_venda": "100",
                  "estoque_minimo": "3", "ativo": True, "controla_lote": True}
        form = ProdutoForm(dados, instance=self.racao)
        self.assertTrue(form.is_valid(), form.errors)
        produto = salvar_produto(form, self.gerente)
        self.assertEqual(produto.lotes.get().quantidade, D("10"))
        self.assertIsNone(produto.lotes.get().validade)


class GestaoTest(BaseTest):
    def test_pagamento_parcial_de_conta_e_saida_unica(self):
        form = ContaPagarForm({"descricao": "Compra de ração", "valor": "200", "vencimento": timezone.localdate(),
                              "fornecedor": self.fornecedor.pk})
        self.assertTrue(form.is_valid(), form.errors)
        conta = salvar_conta(form, self.gerente)
        pagamento = pagar_conta(conta, D("75"), "PIX", self.gerente)
        self.assertEqual(conta.saldo, D("125"))
        self.assertEqual(MovimentoCaixa.objects.count(), 1)
        with self.assertRaises(RegraNegocio):
            pagar_conta(conta, D("126"), "PIX", self.gerente)
        with self.assertRaises(RegraNegocio):
            excluir_movimento(pagamento.movimento, self.gerente)

    def test_importacao_previa_sem_gravacao_e_confirmacao_atomica(self):
        csv = "nome;codigo;preco_venda;preco_custo;categoria\nAdubo;A1;42,50;30,00;Fertilizantes\nSemente;S1;10,00;5,00;Sementes"
        registros = preparar_importacao(csv)
        self.assertEqual(len(registros), 2)
        self.assertEqual(Produto.objects.count(), 1)
        self.assertEqual(confirmar_importacao(csv, False, self.gerente), 2)
        self.assertEqual(Produto.objects.get(codigo="A1").preco_venda, D("42.50"))
        self.assertEqual(Produto.objects.get(codigo="A1").estoque_atual, D("0"))
        with self.assertRaises(RegraNegocio):
            confirmar_importacao("nome;codigo;preco_venda\nBom;B1;20\nRuim;R1;-1", False, self.gerente)
        self.assertFalse(Produto.objects.filter(codigo="B1").exists())

    def test_importacao_nao_sobrescreve_codigo_sem_opcao_e_preserva_saldo(self):
        self.racao.codigo = "123"
        self.racao.save()
        texto = "nome;codigo;preco_venda\nRação atualizada;123;150"
        with self.assertRaises(RegraNegocio):
            confirmar_importacao(texto, False, self.gerente)
        confirmar_importacao(texto, True, self.gerente)
        self.racao.refresh_from_db()
        self.assertEqual(self.racao.estoque_atual, D("10"))
        self.assertEqual(self.racao.preco_venda, D("150"))

    def test_csv_bloqueia_formulas_em_texto_exportado(self):
        self.assertTrue(celula_csv("=HYPERLINK(A1)").startswith("'"))
        self.assertIn(b"'=SUM", exportar_csv(["Nome"], [["=SUM(1+1)"]]))

    def test_relatorio_rateia_centavos_e_preserva_custo_historico(self):
        outro = Produto.objects.create(nome="Semente", preco_venda=D("1"), preco_custo=D("0.50"), estoque_atual=D("10"))
        self.racao.preco_custo = D("0.40")
        self.racao.save()
        venda = registrar_venda(Venda(desconto=D("0.01")), [
            {"produto": p, "quantidade": D("1"), "preco_unitario": D("1")} for p in [self.racao, outro]], self.func)
        self.racao.preco_custo = D("500")
        self.racao.save()
        hoje = timezone.localdate()
        dados = dados_relatorio(*limites(hoje, hoje))
        self.assertEqual(dados["total_vendas"], D("1.99"))
        self.assertEqual(sum((p["receita"] for p in dados["ranking"]), D("0")), venda.total)
        self.assertEqual(dados["lucro_conhecido"], D("1.09"))
        venda.itens.filter(produto=outro).update(preco_custo=None)
        dados = dados_relatorio(*limites(hoje, hoje))
        self.assertEqual(dados["itens_sem_custo"], 1)
        self.assertIsNone(next(p for p in dados["ranking"] if p["produto"] == outro)["lucro"])

    def test_auditoria_registra_autor_e_nao_guarda_senha(self):
        venda = self.vender("1")
        registro = RegistroAuditoria.objects.get(modelo="loja.Venda", objeto_id=str(venda.pk), acao="CRIAR")
        self.assertEqual(registro.usuario, self.func)
        self.assertTrue(RegistroAuditoria.objects.filter(modelo="auth.User").exists())
        for registro in RegistroAuditoria.objects.filter(modelo="auth.User"):
            self.assertNotIn("password", registro.antes)
            self.assertNotIn("password", registro.depois)


class GestaoTelasTest(BaseTest):
    def test_gerente_acessa_telas_e_exportacoes(self):
        self.vender("1")
        self.client.force_login(self.gerente)
        for nome in ["lote_lista", "conta_lista", "conta_nova", "relatorio", "importar_produtos", "auditoria_lista", "usuario_lista", "usuario_novo"]:
            with self.subTest(tela=nome):
                self.assertEqual(self.client.get(reverse(nome)).status_code, 200)
        csv = self.client.get(reverse("relatorio"), {"export": "csv", "tipo": "produtos"})
        self.assertEqual(csv.status_code, 200)
        self.assertIn("text/csv", csv["Content-Type"])
        pdf = self.client.get(reverse("relatorio"), {"export": "pdf", "tipo": "produtos"})
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF-"))

    def test_perfis_bloqueiam_telas_e_servicos(self):
        self.client.force_login(self.func)
        for nome in ["produto_novo", "lote_lista", "conta_lista", "relatorio", "auditoria_lista", "usuario_lista", "fornecedor_lista"]:
            with self.subTest(perfil="caixa", tela=nome):
                self.assertEqual(self.client.get(reverse(nome)).status_code, 403)
        stock = type(self.func).objects.create_user("estoquista")
        PerfilUsuario.objects.create(usuario=stock, cargo="ESTOQUISTA")
        self.client.force_login(stock)
        self.assertEqual(self.client.get(reverse("produto_novo")).status_code, 200)
        for nome in ["caixa", "venda_nova", "cliente_lista", "relatorio"]:
            self.assertEqual(self.client.get(reverse(nome)).status_code, 403)
        with self.assertRaises(RegraNegocio):
            registrar_venda(Venda(), [{"produto": self.racao, "quantidade": D("1"), "preco_unitario": D("100")}], stock)

    def test_preview_csv_e_confirmacao_pela_tela(self):
        self.client.force_login(self.gerente)
        arquivo = SimpleUploadedFile("produtos.csv", b"nome;codigo;preco_venda\nAdubo;AD1;20")
        previa = self.client.post(reverse("importar_produtos"), {"arquivo": arquivo})
        self.assertContains(previa, "Confirmar importação")
        self.assertFalse(Produto.objects.filter(codigo="AD1").exists())
        response = self.client.post(reverse("importar_produtos"), {"confirmar": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Produto.objects.filter(codigo="AD1").exists())
