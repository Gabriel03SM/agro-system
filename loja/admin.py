from django.contrib import admin

from .models import (AlteracaoVenda, Categoria, Cliente, Fornecedor, ItemVenda, MovimentoCaixa,
                     MovimentoEstoque, PagamentoVenda, Produto, RecebimentoFiado, SessaoCaixa, Venda)


class OperacaoAdmin(admin.ModelAdmin):
    """As operações financeiras são alteradas pelos serviços da aplicação."""
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    search_fields = ["nome"]


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ["nome", "codigo", "categoria", "preco_venda", "estoque_atual", "ativo"]
    list_filter = ["ativo", "categoria"]
    search_fields = ["nome", "codigo"]
    readonly_fields = ["estoque_atual"]


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ["nome", "telefone", "ativo"]
    search_fields = ["nome", "documento", "telefone"]


@admin.register(Fornecedor)
class FornecedorAdmin(admin.ModelAdmin):
    list_display = ["nome", "telefone", "ativo"]
    search_fields = ["nome", "documento"]


class ItemInline(admin.TabularInline):
    model = ItemVenda
    extra = 0
    can_delete = False
    readonly_fields = ["produto", "quantidade", "preco_unitario", "desconto", "preco_custo"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Venda)
class VendaAdmin(OperacaoAdmin):
    list_display = ["id", "data", "cliente", "forma_pagamento", "total", "cancelada"]
    list_filter = ["forma_pagamento", "cancelada"]
    inlines = [ItemInline]


@admin.register(MovimentoCaixa)
class MovimentoCaixaAdmin(OperacaoAdmin):
    list_display = ["data", "tipo", "motivo", "descricao", "valor"]
    list_filter = ["tipo", "motivo"]


@admin.register(MovimentoEstoque)
class MovimentoEstoqueAdmin(OperacaoAdmin):
    list_display = ["criado_em", "produto", "quantidade", "motivo", "usuario"]
    list_filter = ["motivo"]


for modelo in (SessaoCaixa, PagamentoVenda, RecebimentoFiado, AlteracaoVenda):
    admin.site.register(modelo, OperacaoAdmin)
