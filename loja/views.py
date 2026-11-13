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
from .models import Categoria, LoteProduto, MovimentoCaixa, MovimentoEstoque, PagamentoVenda, Produto, SessaoCaixa, Venda
from .services import (RegraNegocio, ajustar_estoque, cancelar_venda, corrigir_venda,
                       excluir_movimento, registrar_movimento, registrar_venda)
from .gestao_services import salvar_produto
from .permissoes import cargo_usuario, estoque_required, financeiro_required

ZERO = Decimal("0")


def staff_required(view):
    """Ações sensíveis (cancelar venda, apagar lançamento) só para gerente (is_staff)."""
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if cargo_usuario(request.user) != "GERENTE":
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
    por_forma = {r["forma"]: r["t"] for r in PagamentoVenda.objects.filter(venda__in=vendas).values("forma").annotate(t=Sum("valor"))}
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
    if cargo_usuario(request.user) == "ESTOQUISTA":
        return redirect("lote_lista")
    hoje = timezone.localdate()
    baixo = Produto.objects.filter(ativo=True, estoque_atual__lte=F("estoque_minimo"))
    lotes = LoteProduto.objects.filter(quantidade__gt=0).filter(
        Q(validade__lte=hoje + timedelta(days=30)) | Q(validade__isnull=True)).select_related("produto")
    ctx = {
        "hoje": resumo(*limites(hoje, hoje)),
        "mes": resumo(*limites(hoje.replace(day=1), hoje)),
        "estoque_baixo": baixo.order_by("estoque_atual")[:10],
        "qtd_estoque_baixo": baixo.count(),
        "ultimas_vendas": Venda.objects.all()[:8],
        "lotes_alerta": lotes[:5], "qtd_lotes_alerta": lotes.count(),
    }
    if cargo_usuario(request.user) == "GERENTE":
        from .gestao_views import contas_com_saldo
        ctx["qtd_contas_vencidas"] = contas_com_saldo().filter(restante__gt=0, vencimento__lt=hoje).count()
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


@estoque_required
def produto_novo(request):
    form = ProdutoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            produto = salvar_produto(form, request.user)
        except RegraNegocio as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f"Produto “{produto.nome}” cadastrado.")
            return redirect("produto_lista")
    return render(request, "loja/form.html", {"form": form, "titulo": "Novo produto", "voltar": "produto_lista"})


@estoque_required
def produto_editar(request, pk):
    produto = get_object_or_404(Produto, pk=pk)
    form = ProdutoForm(request.POST or None, instance=produto)
    if request.method == "POST" and form.is_valid():
        try:
            salvar_produto(form, request.user)
        except RegraNegocio as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Produto atualizado.")
            return redirect("produto_lista")
    return render(request, "loja/form.html", {"form": form, "titulo": f"Editar: {produto.nome}", "voltar": "produto_lista"})


@estoque_required
def produto_estoque(request, pk):
    produto = get_object_or_404(Produto, pk=pk)
    form = EstoqueForm(request.POST or None, produto=produto)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            ajustar_estoque(produto, d["tipo"], d["quantidade"], d["observacao"], request.user,
                             fornecedor=d.get("fornecedor"), custo_unitario=d.get("custo_unitario"),
                             lote=d.get("lote"), numero_lote=d.get("numero_lote", ""), validade=d.get("validade"))
        except RegraNegocio as e:
            form.add_error("quantidade", str(e))
        else:
            messages.success(request, "Estoque atualizado.")
            return redirect("produto_lista")
    historico = produto.movimentos.select_related("usuario", "fornecedor")[:15]
    return render(request, "loja/estoque_form.html", {"form": form, "produto": produto, "historico": historico})


# ---------- categorias ----------
@estoque_required
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
@financeiro_required
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


@financeiro_required
def venda_nova(request):
    return _venda_form(request)


@staff_required
def venda_editar(request, pk):
    venda = get_object_or_404(Venda, pk=pk)
    if venda.cancelada or (venda.caixa_id and not venda.caixa.aberto):
        messages.error(request, "Esta venda foi cancelada ou pertence a um caixa fechado.")
        return redirect("venda_detalhe", pk=pk)
    return _venda_form(request, venda)


def _venda_form(request, venda=None):
    if request.method == "POST":
        form = VendaForm(request.POST, instance=venda)
        formset = ItemVendaFormSet(request.POST, prefix="itens", instance=venda)
        if form.is_valid() and formset.is_valid():
            itens = [
                {"produto": c["produto"], "quantidade": c["quantidade"], "preco_unitario": c["preco_unitario"], "desconto": c["desconto"]}
                for c in (f.cleaned_data for f in formset.forms) if c and not c.get("DELETE")
            ]
            try:
                if venda is None:
                    salva = registrar_venda(form.save(commit=False), itens, request.user, form.pagamentos())
                else:
                    salva = corrigir_venda(form.save(commit=False), itens, request.user, form.pagamentos(),
                                            form.cleaned_data["motivo_correcao"], form.cleaned_data["versao"])
            except RegraNegocio as e:
                form.add_error(None, str(e))
            else:
                messages.success(request, f"Venda #{salva.pk} {'corrigida' if venda else 'registrada'}.")
                return redirect("venda_detalhe", pk=salva.pk)
    else:
        form = VendaForm(instance=venda)
        formset = ItemVendaFormSet(prefix="itens", instance=venda)
    return render(request, "loja/venda_form.html", {"form": form, "formset": formset, "venda": venda,
                  "caixa_aberto": SessaoCaixa.objects.filter(aberto=True).first()})


@financeiro_required
def venda_detalhe(request, pk):
    venda = get_object_or_404(Venda.objects.select_related("criado_por", "cliente_cadastro", "caixa"), pk=pk)
    return render(request, "loja/venda_detalhe.html", {"venda": venda, "itens": venda.itens.select_related("produto"),
                  "alteracoes": venda.alteracoes.select_related("usuario")})


@financeiro_required
def venda_comprovante(request, pk):
    venda = get_object_or_404(Venda.objects.select_related("criado_por"), pk=pk)
    return render(request, "loja/comprovante.html", {"venda": venda, "itens": venda.itens.select_related("produto")})


@staff_required
@require_POST
def venda_cancelar(request, pk):
    venda = get_object_or_404(Venda, pk=pk)
    try:
        cancelar_venda(venda, request.user)
    except RegraNegocio as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Venda #{venda.pk} cancelada e estoque devolvido.")
    return redirect("venda_detalhe", pk=pk)


# ---------- caixa ----------
@financeiro_required
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
        "caixa_aberto": SessaoCaixa.objects.filter(aberto=True).select_related("aberto_por").first(),
        "fechamentos": SessaoCaixa.objects.filter(aberto=False).select_related("fechado_por")[:20],
    })


@financeiro_required
def movimento_novo(request):
    tipo = request.GET.get("tipo", "SAIDA")
    form = MovimentoCaixaForm(request.POST or None, initial={"tipo": tipo if tipo in ("ENTRADA", "SAIDA") else "SAIDA"})
    if request.method == "POST" and form.is_valid():
        mov = form.save(commit=False)
        try:
            registrar_movimento(mov, request.user)
        except RegraNegocio as e:
            form.add_error(None, str(e))
        else:
            messages.success(request, "Lançamento registrado no caixa.")
            return redirect("caixa")
    return render(request, "loja/form.html", {"form": form, "titulo": "Lançamento de caixa", "voltar": "caixa"})


@staff_required
def movimento_excluir(request, pk):
    mov = get_object_or_404(MovimentoCaixa, pk=pk)
    if request.method == "POST":
        try:
            excluir_movimento(mov, request.user)
        except RegraNegocio as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "Lançamento excluído.")
        return redirect("caixa")
    return render(request, "loja/confirmar.html", {"texto": f"Excluir o lançamento “{mov.descricao}” de R$ {mov.valor}?", "voltar": "caixa"})
