from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .csv_produtos import CABECALHO, confirmar_importacao, preparar_importacao
from .forms import ContaPagarForm, ImportacaoCSVForm, LoteForm, RecebimentoForm
from .gestao_services import pagar_conta, salvar_conta
from .models import ContaPagar, LoteProduto, RegistroAuditoria
from .permissoes import estoque_required, gerente_required
from .relatorios import dados_relatorio, exportar_csv, exportar_pdf, tabela_exportacao
from .services import RegraNegocio
from .usuarios import UsuarioForm, salvar_usuario
from .views import limites, paginar, parse_data


@estoque_required
def lote_lista(request):
    hoje = timezone.localdate()
    lotes = LoteProduto.objects.select_related("produto")
    filtro = request.GET.get("filtro", "alertas")
    if filtro == "vencidos":
        lotes = lotes.filter(quantidade__gt=0, validade__lt=hoje)
    elif filtro == "sem_validade":
        lotes = lotes.filter(quantidade__gt=0, validade__isnull=True)
    elif filtro != "todos":
        lotes = lotes.filter(quantidade__gt=0).filter(Q(validade__lte=hoje + timedelta(days=30)) | Q(validade__isnull=True))
    q = request.GET.get("q", "").strip()
    if q:
        lotes = lotes.filter(Q(produto__nome__icontains=q) | Q(numero__icontains=q))
    page, qs = paginar(request, lotes)
    return render(request, "loja/lote_lista.html", {"page": page, "qs": qs, "filtro": filtro, "q": q, "hoje": hoje})


@estoque_required
def lote_editar(request, pk):
    lote = get_object_or_404(LoteProduto, pk=pk)
    form = LoteForm(request.POST or None, instance=lote)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Identificação e validade do lote atualizadas.")
        return redirect("lote_lista")
    return render(request, "loja/form.html", {"form": form, "titulo": f"Lote de {lote.produto.nome}", "voltar": "lote_lista"})


def contas_com_saldo():
    return ContaPagar.objects.select_related("fornecedor").prefetch_related("pagamentos").annotate(
        pago=Coalesce(Sum("pagamentos__valor"), Value(Decimal("0")), output_field=DecimalField(max_digits=12, decimal_places=2))
    ).annotate(restante=F("valor") - F("pago")).order_by("vencimento", "pk")


@gerente_required
def conta_lista(request):
    contas = contas_com_saldo()
    filtro = request.GET.get("filtro", "abertas")
    if filtro == "pagas":
        contas = contas.filter(restante__lte=0)
    elif filtro != "todas":
        contas = contas.filter(restante__gt=0)
        if filtro == "vencidas":
            contas = contas.filter(vencimento__lt=timezone.localdate())
    page, qs = paginar(request, contas)
    return render(request, "loja/conta_lista.html", {"page": page, "qs": qs, "filtro": filtro})


@gerente_required
def conta_form(request, pk=None):
    conta = get_object_or_404(ContaPagar, pk=pk) if pk else None
    form = ContaPagarForm(request.POST or None, instance=conta)
    if request.method == "POST" and form.is_valid():
        try:
            conta = salvar_conta(form, request.user)
        except RegraNegocio as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Conta a pagar salva.")
            return redirect("conta_detalhe", pk=conta.pk)
    return render(request, "loja/form.html", {"form": form, "titulo": "Editar conta" if pk else "Nova conta a pagar",
                                              "voltar": "conta_lista"})


@gerente_required
def conta_detalhe(request, pk):
    conta = get_object_or_404(ContaPagar.objects.prefetch_related("pagamentos__movimento"), pk=pk)
    form = RecebimentoForm(request.POST or None, initial={"valor": conta.saldo})
    form.fields["valor"].label = "Valor pago (R$)"
    form.fields["forma"].label = "Forma de pagamento"
    if request.method == "POST" and form.is_valid():
        try:
            pagar_conta(conta, form.cleaned_data["valor"], form.cleaned_data["forma"], request.user)
        except RegraNegocio as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Pagamento registrado e saída lançada no caixa.")
            return redirect("conta_detalhe", pk=pk)
    return render(request, "loja/conta_detalhe.html", {"conta": conta, "form": form})


@gerente_required
def relatorio(request):
    hoje = timezone.localdate()
    de = parse_data(request.GET.get("de"), hoje.replace(day=1))
    ate = parse_data(request.GET.get("ate"), hoje)
    if ate < de:
        de, ate = ate, de
    if (ate - de).days > 366:
        messages.error(request, "Escolha um período de até 366 dias.")
        return redirect("relatorio")
    dados = dados_relatorio(*limites(de, ate))
    formato = request.GET.get("export")
    if formato in ("csv", "pdf"):
        tipo = request.GET.get("tipo", "vendas")
        if tipo not in ("vendas", "produtos", "estoque"):
            tipo = "vendas"
        titulo, cabecalho, linhas = tabela_exportacao(dados, tipo)
        if formato == "csv":
            response = HttpResponse(exportar_csv(cabecalho, linhas), content_type="text/csv; charset=utf-8")
        else:
            response = HttpResponse(exportar_pdf(titulo, cabecalho, linhas, f"{de:%d/%m/%Y} a {ate:%d/%m/%Y}"),
                                    content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{tipo}-{de}-{ate}.{formato}"'
        response["Cache-Control"] = "no-store"
        return response
    return render(request, "loja/relatorio.html", {"r": dados, "de": de, "ate": ate})


@estoque_required
def importar_produtos(request):
    if request.GET.get("modelo"):
        response = HttpResponse(exportar_csv(CABECALHO, [["Ração exemplo 25 kg", "789000000001", "Rações", "SC", "70,00", "100,00", "3", "sim", "sim"]]),
                                content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="modelo-produtos.csv"'
        return response
    form = ImportacaoCSVForm(request.POST or None, request.FILES or None)
    previa = None
    if request.method == "POST":
        if request.POST.get("confirmar"):
            pendente = request.session.get("importacao_produtos")
            if not pendente:
                messages.error(request, "Envie o CSV novamente para conferir os dados.")
            else:
                try:
                    qtd = confirmar_importacao(pendente["texto"], pendente["atualizar"], request.user)
                except RegraNegocio as exc:
                    messages.error(request, str(exc))
                else:
                    request.session.pop("importacao_produtos", None)
                    messages.success(request, f"{qtd} produto(s) importado(s). O estoque existente foi preservado.")
                    return redirect("produto_lista")
        elif form.is_valid():
            request.session.pop("importacao_produtos", None)
            try:
                texto = form.cleaned_data["arquivo"].read().decode("utf-8-sig")
                previa = preparar_importacao(texto, form.cleaned_data["atualizar"])
            except (RegraNegocio, UnicodeDecodeError) as exc:
                form.add_error("arquivo", str(exc) if isinstance(exc, RegraNegocio) else "Salve o arquivo em CSV UTF-8 e tente novamente.")
            else:
                request.session["importacao_produtos"] = {"texto": texto, "atualizar": form.cleaned_data["atualizar"]}
    return render(request, "loja/importacao.html", {"form": form, "previa": previa})


@gerente_required
def auditoria_lista(request):
    registros = RegistroAuditoria.objects.select_related("usuario")
    q = request.GET.get("q", "").strip()
    if q:
        registros = registros.filter(Q(modelo__icontains=q) | Q(usuario__username__icontains=q) | Q(objeto_id=q))
    page, qs = paginar(request, registros, 50)
    return render(request, "loja/auditoria.html", {"page": page, "qs": qs, "q": q})


@gerente_required
def usuario_lista(request):
    usuarios = get_user_model().objects.select_related("perfil_loja").order_by("username")
    return render(request, "loja/usuario_lista.html", {"usuarios": usuarios})


@gerente_required
def usuario_form(request, pk=None):
    alvo = get_object_or_404(get_user_model(), pk=pk) if pk else None
    form = UsuarioForm(request.POST or None, instance=alvo)
    if request.method == "POST" and form.is_valid():
        try:
            alvo = salvar_usuario(form, request.user)
        except RegraNegocio as exc:
            form.add_error(None, str(exc))
        else:
            if alvo.pk == request.user.pk and form.cleaned_data.get("senha"):
                update_session_auth_hash(request, alvo)
            messages.success(request, "Usuário e perfil salvos.")
            return redirect("usuario_lista")
    return render(request, "loja/form.html", {"form": form, "titulo": "Editar usuário" if pk else "Novo usuário",
                                              "voltar": "usuario_lista"})
