from django.db import migrations


def migrar(apps, schema_editor):
    Cliente = apps.get_model("loja", "Cliente")
    Venda = apps.get_model("loja", "Venda")
    Pagamento = apps.get_model("loja", "PagamentoVenda")
    alias = schema_editor.connection.alias
    clientes = {}
    for venda in Venda.objects.using(alias).all().iterator():
        nome = venda.cliente.strip()
        if not nome and venda.forma_pagamento == "FIADO":
            nome = f"Cliente não identificado (venda #{venda.pk})"
        if nome:
            if nome not in clientes:
                cliente = Cliente.objects.using(alias).create(nome=nome,
                    observacao="Cadastro criado a partir das vendas anteriores. Confira os dados e possíveis nomes repetidos.")
                clientes[nome] = cliente.pk
            Venda.objects.using(alias).filter(pk=venda.pk).update(cliente_cadastro_id=clientes[nome])
        Pagamento.objects.using(alias).create(venda_id=venda.pk, forma=venda.forma_pagamento, valor=venda.total)


class Migration(migrations.Migration):
    dependencies = [("loja", "0002_operacao_da_loja")]
    operations = [migrations.RunPython(migrar, migrations.RunPython.noop)]
