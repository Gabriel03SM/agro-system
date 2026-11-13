from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

ZERO = Decimal("0")


class Cliente(models.Model):
    nome = models.CharField("Nome", max_length=120)
    documento = models.CharField("CPF / CNPJ", max_length=25, blank=True)
    telefone = models.CharField("Telefone", max_length=30, blank=True)
    email = models.EmailField("E-mail", blank=True)
    endereco = models.CharField("Endereço", max_length=255, blank=True)
    observacao = models.TextField("Observação", blank=True)
    ativo = models.BooleanField("Ativo", default=True)

    class Meta:
        ordering = ["nome", "id"]

    def __str__(self):
        return self.nome

    @property
    def saldo_devedor(self):
        devido = PagamentoVenda.objects.filter(venda__cliente_cadastro=self, venda__cancelada=False,
                                               forma="FIADO").aggregate(t=models.Sum("valor"))["t"] or ZERO
        recebido = RecebimentoFiado.objects.filter(venda__cliente_cadastro=self).aggregate(
            t=models.Sum("valor"))["t"] or ZERO
        return devido - recebido


class Fornecedor(models.Model):
    nome = models.CharField("Nome / razão social", max_length=150)
    documento = models.CharField("CPF / CNPJ", max_length=25, blank=True)
    telefone = models.CharField("Telefone", max_length=30, blank=True)
    email = models.EmailField("E-mail", blank=True)
    endereco = models.CharField("Endereço", max_length=255, blank=True)
    ativo = models.BooleanField("Ativo", default=True)

    class Meta:
        ordering = ["nome", "id"]

    def __str__(self):
        return self.nome


class SessaoCaixa(models.Model):
    aberto = models.BooleanField(default=True)
    aberto_em = models.DateTimeField(default=timezone.now)
    fechado_em = models.DateTimeField(null=True, blank=True)
    aberto_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="caixas_abertos")
    fechado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.PROTECT, related_name="caixas_fechados")
    troco_inicial = models.DecimalField("Troco inicial (R$)", max_digits=12, decimal_places=2,
                                        validators=[MinValueValidator(ZERO)])
    dinheiro_esperado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    dinheiro_contado = models.DecimalField("Dinheiro contado (R$)", max_digits=12, decimal_places=2,
                                           null=True, blank=True, validators=[MinValueValidator(ZERO)])
    observacao = models.CharField("Observação", max_length=255, blank=True)

    class Meta:
        ordering = ["-aberto_em", "-id"]
        constraints = [models.UniqueConstraint(fields=["aberto"], condition=models.Q(aberto=True),
                                                name="um_caixa_aberto")]

    @property
    def diferenca(self):
        if self.dinheiro_contado is not None and self.dinheiro_esperado is not None:
            return self.dinheiro_contado - self.dinheiro_esperado
        return None

    def __str__(self):
        return f"Caixa #{self.pk}"


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
    estoque_atual = models.DecimalField("Estoque atual", max_digits=12, decimal_places=3, default=ZERO,
                                         validators=[MinValueValidator(ZERO)])
    estoque_minimo = models.DecimalField("Estoque mínimo (alerta)", max_digits=12, decimal_places=3, default=ZERO,
                                         validators=[MinValueValidator(ZERO)])
    ativo = models.BooleanField("Ativo", default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    controla_lote = models.BooleanField("Controlar lote e validade", default=False)

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


class LoteProduto(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="lotes")
    numero = models.CharField("Número do lote", max_length=80)
    validade = models.DateField("Validade", null=True, blank=True)
    quantidade = models.DecimalField("Saldo do lote", max_digits=12, decimal_places=3, default=ZERO)
    custo_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)

    class Meta:
        ordering = ["validade", "id"]
        constraints = [models.UniqueConstraint(fields=["produto", "numero"], name="numero_lote_por_produto"),
                       models.CheckConstraint(condition=models.Q(quantidade__gte=0), name="saldo_lote_nao_negativo")]

    def __str__(self):
        return f"{self.numero} — {self.produto.nome} ({self.quantidade})"

    @property
    def vencido(self):
        return self.validade is not None and self.validade < timezone.localdate()


class Venda(models.Model):
    FORMAS = [
        ("DINHEIRO", "Dinheiro"),
        ("PIX", "Pix"),
        ("DEBITO", "Cartão de débito"),
        ("CREDITO", "Cartão de crédito"),
        ("FIADO", "Fiado (a receber)"),
        ("DIVIDIDO", "Pagamento dividido"),
    ]

    data = models.DateTimeField("Data e hora", default=timezone.now)
    forma_pagamento = models.CharField("Forma de pagamento", max_length=10, choices=FORMAS, default="DINHEIRO")
    cliente = models.CharField("Cliente", max_length=120, blank=True)
    cliente_cadastro = models.ForeignKey(Cliente, verbose_name="Cliente cadastrado", null=True, blank=True,
                                          on_delete=models.PROTECT, related_name="vendas")
    caixa = models.ForeignKey(SessaoCaixa, null=True, blank=True, on_delete=models.PROTECT, related_name="vendas")
    observacao = models.CharField("Observação", max_length=255, blank=True)
    desconto = models.DecimalField("Desconto na venda (R$)", max_digits=12, decimal_places=2,
                                   default=ZERO, validators=[MinValueValidator(ZERO)])
    total = models.DecimalField("Total (R$)", max_digits=12, decimal_places=2, default=ZERO)
    versao = models.PositiveIntegerField(default=1)
    cancelada = models.BooleanField(default=False)
    cancelada_em = models.DateTimeField(null=True, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="vendas")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data", "-id"]

    def __str__(self):
        return f"Venda #{self.pk}"

    @property
    def subtotal(self):
        return sum((item.subtotal for item in self.itens.all()), ZERO)

    @property
    def saldo_fiado(self):
        if self.cancelada:
            return ZERO
        devido = sum((p.valor for p in self.pagamentos.all() if p.forma == "FIADO"), ZERO)
        recebido = sum((r.valor for r in self.recebimentos.all()), ZERO)
        return devido - recebido


class ItemVenda(models.Model):
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name="itens")
    produto = models.ForeignKey(Produto, verbose_name="Produto", on_delete=models.PROTECT, related_name="itens_venda")
    quantidade = models.DecimalField("Quantidade", max_digits=12, decimal_places=3,
                                     validators=[MinValueValidator(Decimal("0.001"))])
    preco_unitario = models.DecimalField("Preço unit. (R$)", max_digits=10, decimal_places=2,
                                         validators=[MinValueValidator(ZERO)])
    desconto = models.DecimalField("Desconto do item (R$)", max_digits=12, decimal_places=2,
                                   default=ZERO, validators=[MinValueValidator(ZERO)])
    preco_custo = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    @property
    def subtotal(self):
        return (self.quantidade * self.preco_unitario).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) - self.desconto

    def __str__(self):
        return f"{self.quantidade} x {self.produto}"


class MovimentoEstoque(models.Model):
    MOTIVOS = [
        ("VENDA", "Venda"),
        ("CANCELAMENTO", "Cancelamento de venda"),
        ("ENTRADA", "Entrada de mercadoria"),
        ("PERDA", "Perda / vencimento"),
        ("AJUSTE", "Ajuste / contagem de estoque"),
        ("CORRECAO", "Correção de venda"),
    ]

    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="movimentos")
    quantidade = models.DecimalField("Quantidade (com sinal)", max_digits=12, decimal_places=3)
    motivo = models.CharField(max_length=15, choices=MOTIVOS)
    observacao = models.CharField(max_length=255, blank=True)
    fornecedor = models.ForeignKey(Fornecedor, null=True, blank=True, on_delete=models.PROTECT, related_name="entradas")
    custo_unitario = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    lote = models.ForeignKey(LoteProduto, null=True, blank=True, on_delete=models.PROTECT, related_name="movimentos")
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
    forma = models.CharField("Forma de pagamento", max_length=10,
                             choices=[f for f in Venda.FORMAS if f[0] not in ("FIADO", "DIVIDIDO")], default="DINHEIRO")
    caixa = models.ForeignKey(SessaoCaixa, null=True, blank=True, on_delete=models.PROTECT, related_name="movimentos")
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="movimentos_caixa")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data", "-id"]

    def __str__(self):
        return f"{self.get_tipo_display()} R$ {self.valor}"


class PagamentoVenda(models.Model):
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name="pagamentos")
    forma = models.CharField(max_length=10, choices=[f for f in Venda.FORMAS if f[0] != "DIVIDIDO"])
    valor = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(ZERO)])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["venda", "forma"], name="uma_forma_por_venda"),
                       models.CheckConstraint(condition=models.Q(valor__gte=0), name="pagamento_nao_negativo")]


class RecebimentoFiado(models.Model):
    venda = models.ForeignKey(Venda, on_delete=models.PROTECT, related_name="recebimentos")
    movimento = models.ForeignKey(MovimentoCaixa, on_delete=models.PROTECT, related_name="baixas_fiado")
    valor = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])


class AlteracaoVenda(models.Model):
    venda = models.ForeignKey(Venda, on_delete=models.PROTECT, related_name="alteracoes")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    criado_em = models.DateTimeField(auto_now_add=True)
    motivo = models.CharField(max_length=255)
    anterior = models.JSONField()

    class Meta:
        ordering = ["-criado_em", "-id"]


class ConsumoLote(models.Model):
    item = models.ForeignKey(ItemVenda, on_delete=models.CASCADE, related_name="consumos_lote")
    lote = models.ForeignKey(LoteProduto, on_delete=models.PROTECT, related_name="consumos")
    quantidade = models.DecimalField(max_digits=12, decimal_places=3)
    custo_unitario = models.DecimalField(max_digits=10, decimal_places=2)


class ContaPagar(models.Model):
    descricao = models.CharField("Descrição", max_length=200)
    fornecedor = models.ForeignKey(Fornecedor, null=True, blank=True, on_delete=models.PROTECT, related_name="contas")
    valor = models.DecimalField("Valor total (R$)", max_digits=12, decimal_places=2,
                                validators=[MinValueValidator(Decimal("0.01"))])
    vencimento = models.DateField("Vencimento")
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["vencimento", "id"]

    @property
    def saldo(self):
        return self.valor - sum((p.valor for p in self.pagamentos.all()), ZERO)

    @property
    def vencida(self):
        return self.vencimento < timezone.localdate() and self.saldo > ZERO

    def __str__(self):
        return self.descricao


class PagamentoConta(models.Model):
    conta = models.ForeignKey(ContaPagar, on_delete=models.PROTECT, related_name="pagamentos")
    movimento = models.OneToOneField(MovimentoCaixa, on_delete=models.PROTECT, related_name="pagamento_conta")
    valor = models.DecimalField(max_digits=12, decimal_places=2)


class PerfilUsuario(models.Model):
    CARGOS = [("GERENTE", "Gerente"), ("CAIXA", "Caixa"), ("ESTOQUISTA", "Estoquista")]
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil_loja")
    cargo = models.CharField("Perfil", max_length=12, choices=CARGOS, default="CAIXA")


class RegistroAuditoria(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    criado_em = models.DateTimeField(auto_now_add=True)
    modelo = models.CharField(max_length=100)
    objeto_id = models.CharField(max_length=80)
    acao = models.CharField(max_length=10)
    antes = models.JSONField(default=dict)
    depois = models.JSONField(default=dict)

    class Meta:
        ordering = ["-criado_em", "-id"]

    @property
    def tipo_registro(self):
        from django.apps import apps
        try:
            return str(apps.get_model(self.modelo)._meta.verbose_name).capitalize()
        except LookupError:
            return self.modelo.split(".")[-1]

    @property
    def mudancas(self):
        from django.apps import apps
        try:
            modelo = apps.get_model(self.modelo)
        except LookupError:
            modelo = None
        resultado = []
        for nome in sorted(set(self.antes) | set(self.depois)):
            if nome in ("id", "criado_em") or self.antes.get(nome) == self.depois.get(nome):
                continue
            rotulo = nome.replace("_", " ").capitalize()
            if modelo:
                try:
                    rotulo = str(modelo._meta.get_field(nome.removesuffix("_id")).verbose_name).capitalize()
                except Exception:
                    pass
            def exibir(valor):
                if valor is None:
                    return "—"
                if isinstance(valor, bool):
                    return "Sim" if valor else "Não"
                return str(valor)
            resultado.append((rotulo, exibir(self.antes.get(nome)), exibir(self.depois.get(nome))))
        return resultado
