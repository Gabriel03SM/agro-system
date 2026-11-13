from decimal import Decimal

from django import forms
from django.db.models import Q
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils import timezone

from .models import Categoria, Cliente, Fornecedor, ItemVenda, MovimentoCaixa, Produto, Venda
from .services import fmt_qtd

FMT = "%Y-%m-%dT%H:%M"


def agora_local():
    return timezone.localtime().replace(second=0, microsecond=0)


class DataHoraField(forms.DateTimeField):
    def __init__(self, **kwargs):
        kwargs.setdefault("widget", forms.DateTimeInput(attrs={"type": "datetime-local"}, format=FMT))
        kwargs.setdefault("input_formats", [FMT, "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"])
        kwargs.setdefault("initial", agora_local)
        super().__init__(**kwargs)


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ["nome"]


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nome", "documento", "telefone", "email", "endereco", "observacao", "ativo"]
        widgets = {"observacao": forms.Textarea(attrs={"rows": 3})}


class FornecedorForm(forms.ModelForm):
    class Meta:
        model = Fornecedor
        fields = ["nome", "documento", "telefone", "email", "endereco", "ativo"]


class ProdutoForm(forms.ModelForm):
    class Meta:
        model = Produto
        fields = ["nome", "codigo", "categoria", "unidade", "preco_custo", "preco_venda",
                  "estoque_atual", "estoque_minimo", "ativo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["estoque_atual"].disabled = True
            self.fields["estoque_atual"].help_text = "Para alterar, use “Ajustar estoque” na lista de produtos."

    def clean_codigo(self):
        return self.cleaned_data.get("codigo") or None


class EstoqueForm(forms.Form):
    TIPOS = [
        ("ENTRADA", "Entrada de mercadoria (soma ao estoque)"),
        ("PERDA", "Perda / vencimento (subtrai do estoque)"),
        ("AJUSTE", "Contagem (define o estoque para este valor)"),
    ]
    tipo = forms.ChoiceField(label="Tipo", choices=TIPOS)
    quantidade = forms.DecimalField(label="Quantidade", max_digits=12, decimal_places=3, min_value=0)
    observacao = forms.CharField(label="Observação", max_length=255, required=False)
    fornecedor = forms.ModelChoiceField(label="Fornecedor (entrada de mercadoria)",
                                        queryset=Fornecedor.objects.filter(ativo=True), required=False)
    custo_unitario = forms.DecimalField(label="Custo unitário da entrada (R$)", max_digits=10, decimal_places=2,
                                        min_value=0, required=False,
                                        help_text="Atualiza o custo do produto para o valor desta compra.")

    def clean(self):
        dados = super().clean()
        if dados.get("tipo") in ("ENTRADA", "PERDA") and dados.get("quantidade") is not None and dados["quantidade"] <= 0:
            self.add_error("quantidade", "Informe uma quantidade maior que zero.")
        if dados.get("tipo") == "ENTRADA":
            for campo in ("fornecedor", "custo_unitario"):
                if dados.get(campo) is None:
                    self.add_error(campo, "Preencha este campo para a entrada de mercadoria.")
        return dados


class VendaForm(forms.ModelForm):
    data = DataHoraField(label="Data e hora")

    class Meta:
        model = Venda
        fields = ["data", "cliente_cadastro", "forma_pagamento", "desconto", "observacao"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente_cadastro"].queryset = Cliente.objects.filter(ativo=True)
        self.fields["cliente_cadastro"].empty_label = "Consumidor sem cadastro (à vista)"
        self.fields["desconto"].required = False
        for codigo, rotulo in Venda.FORMAS:
            if codigo == "DIVIDIDO":
                continue
            campo = forms.DecimalField(label=f"{rotulo} (R$)", max_digits=12, decimal_places=2,
                                        min_value=0, required=False)
            if self.instance.pk:
                campo.initial = next((p.valor for p in self.instance.pagamentos.all() if p.forma == codigo), None)
            self.fields[f"pagamento_{codigo}"] = campo
        if self.instance.pk:
            self.fields["versao"] = forms.IntegerField(widget=forms.HiddenInput, initial=self.instance.versao)
            self.fields["motivo_correcao"] = forms.CharField(label="Motivo da correção", max_length=255)

    def pagamentos(self):
        if self.cleaned_data["forma_pagamento"] != "DIVIDIDO":
            return None
        return [{"forma": codigo, "valor": self.cleaned_data.get(f"pagamento_{codigo}") or 0}
                for codigo, _ in Venda.FORMAS if codigo != "DIVIDIDO"]

    def clean(self):
        dados = super().clean()
        dados["desconto"] = dados.get("desconto") or 0
        tem_fiado = dados.get("forma_pagamento") == "FIADO" or (
            dados.get("forma_pagamento") == "DIVIDIDO" and (dados.get("pagamento_FIADO") or 0) > 0)
        if tem_fiado and not dados.get("cliente_cadastro"):
            self.add_error("cliente_cadastro", "Selecione um cliente cadastrado para vender fiado.")
        return dados


class ProdutoSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        produto = getattr(value, "instance", None)
        if produto is not None:
            option["attrs"]["data-preco"] = str(produto.preco_venda)
            option["attrs"]["data-codigo"] = produto.codigo or ""
            option["attrs"]["data-nome"] = produto.nome
        return option


class ProdutoChoice(forms.ModelChoiceField):
    def label_from_instance(self, p):
        return f"{p.nome} ({p.get_unidade_display()}) — estoque {fmt_qtd(p.estoque_atual)}"


class ItemVendaForm(forms.ModelForm):
    produto = ProdutoChoice(queryset=Produto.objects.none(), widget=ProdutoSelect, label="Produto",
                            empty_label="Selecione o produto…")

    class Meta:
        model = ItemVenda
        fields = ["produto", "quantidade", "preco_unitario", "desconto"]
        widgets = {
            "quantidade": forms.NumberInput(attrs={"step": "any", "min": "0", "inputmode": "decimal"}),
            "preco_unitario": forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = Produto.objects.filter(ativo=True).order_by("nome")
        if self.instance.pk:
            self.fields["produto"].queryset = Produto.objects.filter(
                Q(ativo=True) | Q(pk=self.instance.produto_id)).order_by("nome")
        self.fields["desconto"].required = False

    def clean_desconto(self):
        return self.cleaned_data.get("desconto") or 0


class ItemFormSet(BaseInlineFormSet):
    default_error_messages = {
        **BaseInlineFormSet.default_error_messages,
        "too_few_forms": "Adicione pelo menos um item à venda.",
    }


ItemVendaFormSet = inlineformset_factory(
    Venda, ItemVenda, form=ItemVendaForm, formset=ItemFormSet,
    extra=0, min_num=1, validate_min=True, can_delete=True, max_num=100, validate_max=True,
)


class MovimentoCaixaForm(forms.ModelForm):
    data = DataHoraField(label="Data e hora")

    class Meta:
        model = MovimentoCaixa
        fields = ["tipo", "motivo", "descricao", "valor", "forma", "data"]
        widgets = {"valor": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["motivo"].choices = [m for m in MovimentoCaixa.MOTIVOS if m[0] != "RECEBIMENTO"]


class RecebimentoForm(forms.Form):
    valor = forms.DecimalField(label="Valor recebido (R$)", max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    forma = forms.ChoiceField(label="Forma de recebimento", choices=MovimentoCaixa._meta.get_field("forma").choices)


class RecebimentoAnteriorForm(forms.Form):
    movimento = forms.ModelChoiceField(label="Recebimento anterior à atualização", queryset=MovimentoCaixa.objects.filter(
        caixa__isnull=True, tipo="ENTRADA", motivo="RECEBIMENTO", baixas_fiado__isnull=True))


class AbrirCaixaForm(forms.Form):
    troco_inicial = forms.DecimalField(label="Troco inicial em dinheiro (R$)", max_digits=12, decimal_places=2,
                                       min_value=0, initial=0)


class FecharCaixaForm(forms.Form):
    dinheiro_contado = forms.DecimalField(label="Dinheiro contado na gaveta (R$)", max_digits=12, decimal_places=2, min_value=0)
    observacao = forms.CharField(label="Observação da conferência", max_length=255, required=False)
