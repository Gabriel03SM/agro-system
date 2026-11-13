import csv
from io import StringIO

from django.db import IntegrityError, transaction

from .forms import ProdutoForm
from .auditoria import com_usuario
from .gestao_services import salvar_produto
from .models import Categoria, Produto
from .services import RegraNegocio

CABECALHO = ["nome", "codigo", "categoria", "unidade", "preco_custo", "preco_venda", "estoque_minimo", "controla_lote", "ativo"]


def preparar_importacao(texto, atualizar=False):
    if len(texto.encode("utf-8")) > 1024 * 1024:
        raise RegraNegocio("O CSV deve ter até 1 MB.")
    try:
        delimitador = csv.Sniffer().sniff(texto[:4096], delimiters=";,").delimiter
    except csv.Error:
        delimitador = ";"
    leitor = csv.DictReader(StringIO(texto.lstrip("\ufeff")), delimiter=delimitador)
    colunas = [str(h).strip().lower() for h in (leitor.fieldnames or [])]
    if (not {"nome", "preco_venda"}.issubset(colunas) or len(colunas) != len(set(colunas))
            or set(colunas) - set(CABECALHO)):
        raise RegraNegocio("Cabeçalho inválido. Use o modelo CSV; nome e preco_venda são obrigatórios.")
    leitor.fieldnames = colunas
    resultado, codigos = [], set()
    for numero, linha in enumerate(leitor, 2):
        if not any(linha.values()):
            continue
        if len(resultado) >= 1000 or None in linha:
            raise RegraNegocio(f"Linha {numero}: limite de 1.000 produtos ou quantidade de colunas inválida.")
        dados = {campo: (linha.get(campo) or "").strip() for campo in CABECALHO}
        codigo = dados["codigo"]
        if codigo and codigo in codigos:
            raise RegraNegocio(f"Linha {numero}: código repetido no arquivo: {codigo}.")
        codigos.add(codigo)
        existente = Produto.objects.filter(codigo=codigo).first() if codigo else None
        if existente and not atualizar:
            raise RegraNegocio(f"Linha {numero}: código {codigo} já existe. Marque a opção de atualizar ou corrija o arquivo.")
        if existente:
            for campo in CABECALHO:
                if campo not in colunas:
                    if campo == "categoria":
                        dados[campo] = existente.categoria.nome if existente.categoria_id else ""
                    else:
                        valor = getattr(existente, campo)
                        dados[campo] = ("sim" if valor else "não") if isinstance(valor, bool) else str(valor or "")
        categoria_nome = dados.pop("categoria")
        if len(categoria_nome) > 80:
            raise RegraNegocio(f"Linha {numero}: nome da categoria deve ter até 80 caracteres.")
        categoria = Categoria.objects.filter(nome=categoria_nome).first() if categoria_nome else None
        dados["categoria"] = categoria.pk if categoria else ""
        dados["unidade"] = dados["unidade"] or "UN"
        for campo in ("preco_custo", "preco_venda", "estoque_minimo"):
            dados[campo] = dados[campo].replace(",", ".") or ("" if campo == "preco_venda" else "0")
        for campo in ("ativo", "controla_lote"):
            valor = dados[campo].lower()
            if valor and valor not in ("sim", "não", "nao", "true", "false", "1", "0"):
                raise RegraNegocio(f"Linha {numero}: {campo} deve ser sim ou não.")
            dados[campo] = valor in ("sim", "true", "1") if valor else campo == "ativo"
        dados["estoque_atual"] = str(existente.estoque_atual) if existente else "0"
        form = ProdutoForm(dados, instance=existente)
        if not form.is_valid():
            erros = "; ".join(f"{campo}: {', '.join(mensagens)}" for campo, mensagens in form.errors.items())
            raise RegraNegocio(f"Linha {numero}: {erros}")
        resultado.append({"dados": dados, "categoria_nome": categoria_nome, "existente": existente.pk if existente else None,
                          "acao": "Atualizar" if existente else "Criar"})
    if not resultado:
        raise RegraNegocio("O arquivo não contém produtos.")
    return resultado


@transaction.atomic
@com_usuario
def confirmar_importacao(texto, atualizar, usuario):
    registros = preparar_importacao(texto, atualizar)
    try:
        with transaction.atomic():
            for registro in registros:
                dados = registro["dados"]
                if registro["categoria_nome"]:
                    categoria, _ = Categoria.objects.get_or_create(nome=registro["categoria_nome"])
                    dados["categoria"] = categoria.pk
                existente = Produto.objects.select_for_update().get(pk=registro["existente"]) if registro["existente"] else None
                form = ProdutoForm(dados, instance=existente)
                if not form.is_valid():
                    raise RegraNegocio("O catálogo mudou desde a conferência. Envie o arquivo novamente.")
                salvar_produto(form, usuario)
    except IntegrityError:
        raise RegraNegocio("Um código foi cadastrado durante a importação. Confira o catálogo e tente novamente.") from None
    return len(registros)
