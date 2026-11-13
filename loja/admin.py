from django.contrib import admin

from .models import Categoria, ItemVenda, MovimentoCaixa, MovimentoEstoque, Produto, Venda


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    search_fields = ["nome"]


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ["nome", "codigo", "categoria", "preco_venda", "estoque_atual", "ativo"]
    list_filter = ["ativo", "categoria"]
    search_fields = ["nome", "codigo"]


class ItemInline(admin.TabularInline):
    model = ItemVenda
    extra = 0


@admin.register(Venda)
class VendaAdmin(admin.ModelAdmin):
    list_display = ["id", "data", "cliente", "forma_pagamento", "total", "cancelada"]
    list_filter = ["forma_pagamento", "cancelada"]
    inlines = [ItemInline]


@admin.register(MovimentoCaixa)
class MovimentoCaixaAdmin(admin.ModelAdmin):
    list_display = ["data", "tipo", "motivo", "descricao", "valor"]
    list_filter = ["tipo", "motivo"]


@admin.register(MovimentoEstoque)
class MovimentoEstoqueAdmin(admin.ModelAdmin):
    list_display = ["criado_em", "produto", "quantidade", "motivo", "usuario"]
    list_filter = ["motivo"]
