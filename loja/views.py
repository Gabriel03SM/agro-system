from datetime import datetime, time, timedelta
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (CategoriaForm, EstoqueForm, ItemVendaFormSet, MovimentoCaixaForm, ProdutoForm, VendaForm)
from .models import Categoria, MovimentoCaixa, MovimentoEstoque, Produto, Venda
from .services import EstoqueInsuficiente, ajustar_estoque, cancelar_venda, registrar_venda

ZERO = Decimal("0")


def staff_required(view):
    """Ações sensíveis (cancelar venda, apagar lançamento) só para gerente (is_staff)."""
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


# ---------- utilidades ----------
def paginar(request, queryset, por_pagina=25):
    page = Paginator(queryset, por_pagina).get_page(request.GET.get("page"))
    qs = request.GET.copy()
    qs.pop("page", None)
    return page, qs.urlencode()


def parse_data(texto, padrao):
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return padrao


def limites(de, ate):
    tz = timezone.get_current_timezone()
    ini = timezone.make_aware(datetime.combine(de, time.min), tz)
    fim = timezone.make_aware(datetime.combine(ate + timedelta(days=1), time.min), tz)
    return ini, fim


def resumo(ini, fim):
    vendas = Venda.objects.filter(cancelada=False, data__gte=ini, data__lt=fim)
    mov = MovimentoCaixa.objects.filter(data__gte=ini, data__lt=fim)
    por_forma = {r["forma_pagamento"]: r["t"] for r in vendas.values("forma_pagamento").annotate(t=Sum("total"))}
    total_vendas = sum(por_forma.values(), ZERO)
    fiado = por_forma.get("FIADO", ZERO)
    recebido = total_vendas - fiado
    entradas = mov.filter(tipo="ENTRADA").aggregate(t=Sum("valor"))["t"] or ZERO
    saidas = mov.filter(tipo="SAIDA").aggregate(t=Sum("valor"))["t"] or ZERO
    return {
        "qtd_vendas": vendas.count(),
        "total_vendas": total_vendas,
        "fiado": fiado,
        "recebido": recebido,
        "entradas": entradas,
        "saidas": saidas,
        "saldo": recebido + entradas - saidas,
        "por_forma": [(rotulo, por_forma[cod]) for cod, rotulo in Venda.FORMAS if cod in por_forma],
    }


# ---------- dashboard ----------
@login_required
def dashboard(request):
    hoje = timezone.localdate()
    baixo = Produto.objects.filter(ativo=True, estoque_atual__lte=F("estoque_minimo"))
    ctx = {
        "hoje": resumo(*limites(hoje, hoje)),
        "mes": resumo(*limites(hoje.replace(day=1), hoje)),
        "estoque_baixo": baixo.order_by("estoque_atual")[:10],
        "qtd_estoque_baixo": baixo.count(),
        "ultimas_vendas": Venda.objects.all()[:8],
    }
    return render(request, "loja/dashboard.html", ctx)


# ---------- produtos ----------
@login_required
def produto_lista(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "ativos")
    produtos = Produto.objects.select_related("categoria")
    if status == "ativos":
        produtos = produtos.filter(ativo=True)
    elif status == "inativos":
        produtos = produtos.filter(ativo=False)
    if q:
        produtos = produtos.filter(Q(nome__icontains=q) | Q(codigo__icontains=q))
    if request.GET.get("baixo"):
        produtos = produtos.filter(estoque_atual__lte=F("estoque_minimo"))
    page, qs = paginar(request, produtos)
    return render(request, "loja/produto_lista.html",
                  {"page": page, "qs": qs, "q": q, "status": status, "baixo": request.GET.get("baixo")})


@login_required
def produto_novo(request):
    form = ProdutoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        produto = form.save()
        if produto.estoque_atual:
            MovimentoEstoque.objects.create(produto=produto, quantidade=produto.estoque_atual, motivo="AJUSTE",
                                            observacao="Estoque inicial", usuario=request.user)
        messages.success(request, f"Produto “{produto.nome}” cadastrado.")
        return redirect("produto_lista")
    return render(request, "loja/form.html", {"form": form, "titulo": "Novo produto", "voltar": "produto_lista"})


@login_required
def produto_editar(request, pk):
    produto = get_object_or_404(Produto, pk=pk)
    form = ProdutoForm(request.POST or None, instance=produto)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Produto atualizado.")
        return redirect("produto_lista")
    return render(request, "loja/form.html", {"form": form, "titulo": f"Editar: {produto.nome}", "voltar": "produto_lista"})


@login_required
def produto_estoque(request, pk):
    produto = get_object_or_404(Produto, pk=pk)
    form = EstoqueForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            ajustar_estoque(produto, d["tipo"], d["quantidade"], d["observacao"], request.user)
        except EstoqueInsuficiente as e:
            form.add_error("quantidade", str(e))
        else:
            messages.success(request, "Estoque atualizado.")
            return redirect("produto_lista")
    historico = produto.movimentos.select_related("usuario")[:15]
    return render(request, "loja/estoque_form.html", {"form": form, "produto": produto, "historico": historico})


# ---------- categorias ----------
@login_required
def categoria_lista(request):
    form = CategoriaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Categoria criada.")
        return redirect("categoria_lista")
    from django.db.models import Count
    categorias = Categoria.objects.annotate(qtd=Count("produtos"))
    return render(request, "loja/categoria_lista.html", {"form": form, "categorias": categorias})


@staff_required
@require_POST
def categoria_excluir(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    categoria.delete()  # produtos ficam sem categoria (SET_NULL)
    messages.success(request, "Categoria excluída.")
    return redirect("categoria_lista")


# ---------- vendas ----------
@login_required
def venda_lista(request):
    vendas = Venda.objects.select_related("criado_por")
    q = request.GET.get("q", "").strip()
    de = parse_data(request.GET.get("de"), None)
    ate = parse_data(request.GET.get("ate"), None)
    forma = request.GET.get("forma", "")
    if q:
        vendas = vendas.filter(Q(cliente__icontains=q) | Q(observacao__icontains=q))
    if de:
        vendas = vendas.filter(data__gte=limites(de, de)[0])
    if ate:
        vendas = vendas.filter(data__lt=limites(ate, ate)[1])
    if forma:
        vendas = vendas.filter(forma_pagamento=forma)
    page, qs = paginar(request, vendas)
    return render(request, "loja/venda_lista.html", {
        "page": page, "qs": qs, "q": q, "de": request.GET.get("de", ""), "ate": request.GET.get("ate", ""),
        "forma": forma, "formas": Venda.FORMAS,
    })


@login_required
def venda_nova(request):
    if request.method == "POST":
        form = VendaForm(request.POST)
        formset = ItemVendaFormSet(request.POST, prefix="itens")
        if form.is_valid() and formset.is_valid():
            itens = [
                {"produto": c["produto"], "quantidade": c["quantidade"], "preco_unitario": c["preco_unitario"]}
                for c in (f.cleaned_data for f in formset.forms) if c
            ]
            try:
                venda = registrar_venda(form.save(commit=False), itens, request.user)
            except EstoqueInsuficiente as e:
                form.add_error(None, str(e))
            else:
                messages.success(request, f"Venda #{venda.pk} registrada.")
                return redirect("venda_detalhe", pk=venda.pk)
    else:
        form = VendaForm()
        formset = ItemVendaFormSet(prefix="itens")
    return render(request, "loja/venda_form.html", {"form": form, "formset": formset})


@login_required
def venda_detalhe(request, pk):
    venda = get_object_or_404(Venda.objects.select_related("criado_por"), pk=pk)
    return render(request, "loja/venda_detalhe.html", {"venda": venda, "itens": venda.itens.select_related("produto")})


@staff_required
@require_POST
def venda_cancelar(request, pk):
    venda = get_object_or_404(Venda, pk=pk)
    cancelar_venda(venda, request.user)
    messages.success(request, f"Venda #{venda.pk} cancelada e estoque devolvido.")
    return redirect("venda_detalhe", pk=pk)


# ---------- caixa ----------
@login_required
def caixa(request):
    hoje = timezone.localdate()
    de = parse_data(request.GET.get("de"), hoje)
    ate = parse_data(request.GET.get("ate"), hoje)
    if ate < de:
        de, ate = ate, de
    ini, fim = limites(de, ate)
    movimentos = MovimentoCaixa.objects.filter(data__gte=ini, data__lt=fim).select_related("criado_por")
    return render(request, "loja/caixa.html", {
        "de": de, "ate": ate, "r": resumo(ini, fim), "movimentos": movimentos,
    })


@login_required
def movimento_novo(request):
    tipo = request.GET.get("tipo", "SAIDA")
    form = MovimentoCaixaForm(request.POST or None, initial={"tipo": tipo if tipo in ("ENTRADA", "SAIDA") else "SAIDA"})
    if request.method == "POST" and form.is_valid():
        mov = form.save(commit=False)
        mov.criado_por = request.user
        mov.save()
        messages.success(request, "Lançamento registrado no caixa.")
        return redirect("caixa")
    return render(request, "loja/form.html", {"form": form, "titulo": "Lançamento de caixa", "voltar": "caixa"})


@staff_required
def movimento_excluir(request, pk):
    mov = get_object_or_404(MovimentoCaixa, pk=pk)
    if request.method == "POST":
        mov.delete()
        messages.success(request, "Lançamento excluído.")
        return redirect("caixa")
    return render(request, "loja/confirmar.html", {"texto": f"Excluir o lançamento “{mov.descricao}” de R$ {mov.valor}?", "voltar": "caixa"})
