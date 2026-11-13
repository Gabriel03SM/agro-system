from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class MigracaoOperacaoTest(TransactionTestCase):
    def test_vendas_antigas_preservam_clientes_pagamentos_e_cancelamentos(self):
        executor = MigrationExecutor(connection)
        atuais = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([("loja", "0001_initial")])
            apps = executor.loader.project_state([("loja", "0001_initial")]).apps
            Venda = apps.get_model("loja", "Venda")
            fiado = Venda.objects.create(cliente="Ana", forma_pagamento="FIADO", total="125.50")
            cancelada = Venda.objects.create(cliente="Ana", forma_pagamento="FIADO", total="50", cancelada=True)
            anonima = Venda.objects.create(forma_pagamento="FIADO", total="20")
            dinheiro = Venda.objects.create(forma_pagamento="DINHEIRO", total="10")
            executor = MigrationExecutor(connection)
            executor.migrate([("loja", "0003_migrar_clientes_pagamentos")])
            apps = executor.loader.project_state([("loja", "0003_migrar_clientes_pagamentos")]).apps
            Venda = apps.get_model("loja", "Venda")
            Pagamento = apps.get_model("loja", "PagamentoVenda")
            fiado_novo = Venda.objects.get(pk=fiado.pk)
            self.assertEqual(fiado_novo.cliente_cadastro.nome, "Ana")
            self.assertEqual(Venda.objects.get(pk=cancelada.pk).cliente_cadastro_id, fiado_novo.cliente_cadastro_id)
            self.assertTrue(Venda.objects.get(pk=cancelada.pk).cancelada)
            self.assertIsNotNone(Venda.objects.get(pk=anonima.pk).cliente_cadastro_id)
            self.assertIsNone(Venda.objects.get(pk=dinheiro.pk).cliente_cadastro_id)
            self.assertEqual(str(Pagamento.objects.get(venda_id=fiado.pk).valor), "125.50")
            self.assertEqual(Pagamento.objects.count(), 4)
        finally:
            MigrationExecutor(connection).migrate(atuais)
