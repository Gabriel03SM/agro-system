from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils import timezone

from .models import Categoria, ItemVenda, MovimentoCaixa, Produto, Venda
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


class EstoqueForm(forms.Form):
    TIPOS = [
        ("ENTRADA", "Entrada de mercadoria (soma ao estoque)"),
        ("PERDA", "Perda / vencimento (subtrai do estoque)"),
        ("AJUSTE", "Contagem (define o estoque para este valor)"),
    ]
    tipo = forms.ChoiceField(label="Tipo", choices=TIPOS)
    quantidade = forms.DecimalField(label="Quantidade", max_digits=12, decimal_places=3, min_value=0)
    observacao = forms.CharField(label="Observação", max_length=255, required=False)

    def clean(self):
        dados = super().clean()
        if dados.get("tipo") in ("ENTRADA", "PERDA") and dados.get("quantidade") is not None and dados["quantidade"] <= 0:
            self.add_error("quantidade", "Informe uma quantidade maior que zero.")
        return dados


class VendaForm(forms.ModelForm):
    data = DataHoraField(label="Data e hora")

    class Meta:
        model = Venda
        fields = ["data", "forma_pagamento", "cliente", "observacao"]

    def clean(self):
        dados = super().clean()
        if dados.get("forma_pagamento") == "FIADO" and not dados.get("cliente"):
            self.add_error("cliente", "Informe o nome do cliente para venda fiado.")
        return dados


class ProdutoSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        produto = getattr(value, "instance", None)
        if produto is not None:
            option["attrs"]["data-preco"] = str(produto.preco_venda)
        return option


class ProdutoChoice(forms.ModelChoiceField):
    def label_from_instance(self, p):
        return f"{p.nome} ({p.get_unidade_display()}) — estoque {fmt_qtd(p.estoque_atual)}"


class ItemVendaForm(forms.ModelForm):
    produto = ProdutoChoice(queryset=Produto.objects.none(), widget=ProdutoSelect, label="Produto",
                            empty_label="Selecione o produto…")

    class Meta:
        model = ItemVenda
        fields = ["produto", "quantidade", "preco_unitario"]
        widgets = {
            "quantidade": forms.NumberInput(attrs={"step": "any", "min": "0", "inputmode": "decimal"}),
            "preco_unitario": forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = Produto.objects.filter(ativo=True).order_by("nome")


class ItemFormSet(BaseInlineFormSet):
    default_error_messages = {
        **BaseInlineFormSet.default_error_messages,
        "too_few_forms": "Adicione pelo menos um item à venda.",
    }


ItemVendaFormSet = inlineformset_factory(
    Venda, ItemVenda, form=ItemVendaForm, formset=ItemFormSet,
    extra=0, min_num=1, validate_min=True, can_delete=False,
)


class MovimentoCaixaForm(forms.ModelForm):
    data = DataHoraField(label="Data e hora")

    class Meta:
        model = MovimentoCaixa
        fields = ["tipo", "motivo", "descricao", "valor", "data"]
        widgets = {"valor": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal"})}
