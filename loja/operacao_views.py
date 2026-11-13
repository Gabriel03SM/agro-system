from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from .forms import AbrirCaixaForm, ClienteForm, FecharCaixaForm, FornecedorForm, RecebimentoAnteriorForm, RecebimentoForm
from .models import Cliente, Fornecedor, PagamentoVenda, RecebimentoFiado, SessaoCaixa
from .services import (RegraNegocio, abrir_caixa, dinheiro_no_caixa, fechar_caixa,
                       receber_fiado, vincular_recebimento_anterior)
from .views import paginar

ZERO = Decimal("0")


@login_required
def cliente_lista(request):
    q = request.GET.get("q", "").strip()
    clientes = Cliente.objects.all()
    if q:
        clientes = clientes.filter(Q(nome__icontains=q) | Q(documento__icontains=q) | Q(telefone__icontains=q))
    devidos = dict(PagamentoVenda.objects.filter(forma="FIADO", venda__cancelada=False).values(
        "venda__cliente_cadastro_id").annotate(t=Sum("valor")).values_list("venda__cliente_cadastro_id", "t"))
    recebidos = dict(RecebimentoFiado.objects.values("venda__cliente_cadastro_id").annotate(
        t=Sum("valor")).values_list("venda__cliente_cadastro_id", "t"))
    if request.GET.get("devedores"):
        clientes = clientes.filter(pk__in=[pk for pk, valor in devidos.items() if valor > recebidos.get(pk, ZERO)])
    page, qs = paginar(request, clientes)
    for cliente in page:
        cliente.saldo = devidos.get(cliente.pk, ZERO) - recebidos.get(cliente.pk, ZERO)
    return render(request, "loja/cliente_lista.html", {"page": page, "qs": qs, "q": q,
        "devedores": request.GET.get("devedores"), "total_devedor": sum(devidos.values(), ZERO) - sum(recebidos.values(), ZERO)})


@login_required
def cliente_form(request, pk=None):
    cliente = get_object_or_404(Cliente, pk=pk) if pk else None
    form = ClienteForm(request.POST or None, instance=cliente)
    if request.method == "POST" and form.is_valid():
        cliente = form.save()
        messages.success(request, "Cadastro do cliente salvo.")
        return redirect("cliente_detalhe", pk=cliente.pk)
    return render(request, "loja/form.html", {"form": form, "titulo": "Editar cliente" if pk else "Novo cliente",
                                              "voltar": "cliente_lista"})


@login_required
def cliente_detalhe(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    vincular = request.POST.get("acao") == "vincular_anterior"
    form = RecebimentoForm(request.POST if request.method == "POST" and not vincular else None,
                           initial={"valor": cliente.saldo_devedor})
    anterior = RecebimentoAnteriorForm(request.POST if vincular else None, prefix="anterior") if request.user.is_staff else None
    if vincular and anterior and anterior.is_valid():
        try:
            vincular_recebimento_anterior(cliente, anterior.cleaned_data["movimento"], request.user)
        except RegraNegocio as exc:
            anterior.add_error(None, str(exc))
        else:
            messages.success(request, "Recebimento anterior vinculado, sem duplicar a entrada no caixa.")
            return redirect("cliente_detalhe", pk=pk)
    if request.method == "POST" and not vincular and form.is_valid():
        try:
            receber_fiado(cliente, form.cleaned_data["valor"], form.cleaned_data["forma"], request.user)
        except RegraNegocio as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Pagamento recebido e saldo devedor atualizado.")
            return redirect("cliente_detalhe", pk=pk)
    vendas = cliente.vendas.prefetch_related("pagamentos", "recebimentos").filter(cancelada=False)
    return render(request, "loja/cliente_detalhe.html", {"cliente": cliente, "form": form,
        "anterior": anterior,
        "vendas": vendas, "recebimentos": RecebimentoFiado.objects.filter(venda__cliente_cadastro=cliente).select_related(
            "venda", "movimento__criado_por").order_by("-movimento__data", "-id")})


@login_required
def fornecedor_lista(request):
    q = request.GET.get("q", "").strip()
    fornecedores = Fornecedor.objects.all()
    if q:
        fornecedores = fornecedores.filter(Q(nome__icontains=q) | Q(documento__icontains=q))
    page, qs = paginar(request, fornecedores)
    return render(request, "loja/fornecedor_lista.html", {"page": page, "qs": qs, "q": q})


@login_required
def fornecedor_form(request, pk=None):
    fornecedor = get_object_or_404(Fornecedor, pk=pk) if pk else None
    form = FornecedorForm(request.POST or None, instance=fornecedor)
    if request.method == "POST" and form.is_valid():
        fornecedor = form.save()
        messages.success(request, "Cadastro do fornecedor salvo.")
        return redirect("fornecedor_detalhe", pk=fornecedor.pk)
    return render(request, "loja/form.html", {"form": form, "titulo": "Editar fornecedor" if pk else "Novo fornecedor",
                                              "voltar": "fornecedor_lista"})


@login_required
def fornecedor_detalhe(request, pk):
    fornecedor = get_object_or_404(Fornecedor, pk=pk)
    page, qs = paginar(request, fornecedor.entradas.select_related("produto", "usuario"))
    return render(request, "loja/fornecedor_detalhe.html", {"fornecedor": fornecedor, "page": page, "qs": qs})


@login_required
def caixa_abrir(request):
    form = AbrirCaixaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            abrir_caixa(form.cleaned_data["troco_inicial"], request.user)
        except RegraNegocio as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Caixa aberto. Você já pode registrar vendas.")
            return redirect("caixa")
    return render(request, "loja/form.html", {"form": form, "titulo": "Abrir caixa", "voltar": "caixa"})


@login_required
def caixa_fechar(request, pk):
    caixa = get_object_or_404(SessaoCaixa, pk=pk)
    form = FecharCaixaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            fechar_caixa(caixa, form.cleaned_data["dinheiro_contado"], request.user, form.cleaned_data["observacao"])
        except RegraNegocio as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Caixa fechado. A conferência ficou salva no histórico.")
            return redirect("caixa")
    return render(request, "loja/caixa_fechar.html", {"form": form, "caixa": caixa,
                                                     "esperado": dinheiro_no_caixa(caixa)})
