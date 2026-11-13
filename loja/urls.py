from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("produtos/", views.produto_lista, name="produto_lista"),
    path("produtos/novo/", views.produto_novo, name="produto_novo"),
    path("produtos/<int:pk>/editar/", views.produto_editar, name="produto_editar"),
    path("produtos/<int:pk>/estoque/", views.produto_estoque, name="produto_estoque"),
    path("categorias/", views.categoria_lista, name="categoria_lista"),
    path("categorias/<int:pk>/excluir/", views.categoria_excluir, name="categoria_excluir"),
    path("vendas/", views.venda_lista, name="venda_lista"),
    path("vendas/nova/", views.venda_nova, name="venda_nova"),
    path("vendas/<int:pk>/", views.venda_detalhe, name="venda_detalhe"),
    path("vendas/<int:pk>/cancelar/", views.venda_cancelar, name="venda_cancelar"),
    path("caixa/", views.caixa, name="caixa"),
    path("caixa/lancar/", views.movimento_novo, name="movimento_novo"),
    path("caixa/<int:pk>/excluir/", views.movimento_excluir, name="movimento_excluir"),
]
