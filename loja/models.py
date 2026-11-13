from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

ZERO = Decimal("0")


class Categoria(models.Model):
    nome = models.CharField("Nome", max_length=80, unique=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Produto(models.Model):
    UNIDADES = [
        ("UN", "Unidade"),
        ("KG", "Quilo (kg)"),
        ("SC", "Saco"),
        ("L", "Litro"),
        ("CX", "Caixa"),
        ("PCT", "Pacote"),
        ("M", "Metro"),
    ]

    nome = models.CharField("Nome", max_length=150)
    codigo = models.CharField("Código / código de barras", max_length=40, unique=True, null=True, blank=True)
    categoria = models.ForeignKey(
        Categoria, verbose_name="Categoria", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="produtos",
    )
    unidade = models.CharField("Unidade", max_length=3, choices=UNIDADES, default="UN")
    preco_custo = models.DecimalField("Preço de custo (R$)", max_digits=10, decimal_places=2, default=ZERO,
                                      validators=[MinValueValidator(ZERO)])
    preco_venda = models.DecimalField("Preço de venda (R$)", max_digits=10, decimal_places=2,
                                      validators=[MinValueValidator(ZERO)])
    estoque_atual = models.DecimalField("Estoque atual", max_digits=12, decimal_places=3, default=ZERO)
    estoque_minimo = models.DecimalField("Estoque mínimo (alerta)", max_digits=12, decimal_places=3, default=ZERO,
                                         validators=[MinValueValidator(ZERO)])
    ativo = models.BooleanField("Ativo", default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    @property
    def estoque_baixo(self):
        return self.estoque_atual <= self.estoque_minimo

    @property
    def margem(self):
        if self.preco_venda and self.preco_venda > 0:
            return (self.preco_venda - self.preco_custo) / self.preco_venda * 100
        return None


class Venda(models.Model):
    FORMAS = [
        ("DINHEIRO", "Dinheiro"),
        ("PIX", "Pix"),
        ("DEBITO", "Cartão de débito"),
        ("CREDITO", "Cartão de crédito"),
        ("FIADO", "Fiado (a receber)"),
    ]

    data = models.DateTimeField("Data e hora", default=timezone.now)
    forma_pagamento = models.CharField("Forma de pagamento", max_length=10, choices=FORMAS, default="DINHEIRO")
    cliente = models.CharField("Cliente", max_length=120, blank=True)
    observacao = models.CharField("Observação", max_length=255, blank=True)
    total = models.DecimalField("Total (R$)", max_digits=12, decimal_places=2, default=ZERO)
    cancelada = models.BooleanField(default=False)
    cancelada_em = models.DateTimeField(null=True, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="vendas")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data", "-id"]

    def __str__(self):
        return f"Venda #{self.pk}"


class ItemVenda(models.Model):
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name="itens")
    produto = models.ForeignKey(Produto, verbose_name="Produto", on_delete=models.PROTECT, related_name="itens_venda")
    quantidade = models.DecimalField("Quantidade", max_digits=12, decimal_places=3,
                                     validators=[MinValueValidator(Decimal("0.001"))])
    preco_unitario = models.DecimalField("Preço unit. (R$)", max_digits=10, decimal_places=2,
                                         validators=[MinValueValidator(ZERO)])

    @property
    def subtotal(self):
        return (self.quantidade * self.preco_unitario).quantize(Decimal("0.01"))

    def __str__(self):
        return f"{self.quantidade} x {self.produto}"


class MovimentoEstoque(models.Model):
    MOTIVOS = [
        ("VENDA", "Venda"),
        ("CANCELAMENTO", "Cancelamento de venda"),
        ("ENTRADA", "Entrada de mercadoria"),
        ("PERDA", "Perda / vencimento"),
        ("AJUSTE", "Ajuste / contagem de estoque"),
    ]

    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="movimentos")
    quantidade = models.DecimalField("Quantidade (com sinal)", max_digits=12, decimal_places=3)
    motivo = models.CharField(max_length=15, choices=MOTIVOS)
    observacao = models.CharField(max_length=255, blank=True)
    venda = models.ForeignKey(Venda, null=True, blank=True, on_delete=models.SET_NULL, related_name="movimentos")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-id"]


class MovimentoCaixa(models.Model):
    TIPOS = [("ENTRADA", "Entrada"), ("SAIDA", "Saída")]
    MOTIVOS = [
        ("FORNECEDOR", "Pagamento a fornecedor"),
        ("DESPESA", "Despesa da loja"),
        ("SALARIO", "Salário / diária"),
        ("RETIRADA", "Retirada do dono"),
        ("RECEBIMENTO", "Recebimento de fiado"),
        ("OUTROS", "Outros"),
    ]

    tipo = models.CharField("Tipo", max_length=7, choices=TIPOS)
    motivo = models.CharField("Motivo", max_length=12, choices=MOTIVOS, default="OUTROS")
    descricao = models.CharField("Descrição", max_length=200)
    valor = models.DecimalField("Valor (R$)", max_digits=12, decimal_places=2,
                                validators=[MinValueValidator(Decimal("0.01"))])
    data = models.DateTimeField("Data e hora", default=timezone.now)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="movimentos_caixa")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data", "-id"]

    def __str__(self):
        return f"{self.get_tipo_display()} R$ {self.valor}"
