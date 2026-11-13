import csv
from collections import defaultdict
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from io import BytesIO, StringIO
from pathlib import Path
from xml.sax.saxutils import escape

from django.conf import settings
from django.utils import timezone

from .models import Produto, Venda

ZERO = Decimal("0")
CENTAVO = Decimal("0.01")


def distribuir_desconto(itens, desconto):
    """Distribui centavos proporcionalmente, preservando exatamente o total da venda."""
    subtotal = sum((i.subtotal for i in itens), ZERO)
    if not subtotal:
        return [ZERO] * len(itens)
    proporcionais = [desconto * i.subtotal / subtotal for i in itens]
    partes = [v.quantize(CENTAVO, rounding=ROUND_DOWN) for v in proporcionais]
    centavos = int((desconto - sum(partes, ZERO)) / CENTAVO)
    ordem = sorted(range(len(itens)), key=lambda n: proporcionais[n] - partes[n], reverse=True)
    for n in ordem[:centavos]:
        partes[n] += CENTAVO
    return partes


def dados_relatorio(ini, fim):
    vendas = Venda.objects.filter(cancelada=False, data__gte=ini, data__lt=fim).prefetch_related(
        "itens__produto", "itens__consumos_lote", "pagamentos").order_by("data", "id")
    produtos, dias, linhas_vendas = {}, defaultdict(lambda: {"qtd": 0, "total": ZERO}), []
    sem_custo, lucro_conhecido, total = 0, ZERO, ZERO
    for venda in vendas:
        itens = list(venda.itens.all())
        descontos = distribuir_desconto(itens, venda.desconto)
        total += venda.total
        dia = timezone.localtime(venda.data).date()
        dias[dia]["qtd"] += 1
        dias[dia]["total"] += venda.total
        linhas_vendas.append([venda.pk, timezone.localtime(venda.data).strftime("%d/%m/%Y %H:%M"),
                              venda.cliente or "Consumidor", venda.get_forma_pagamento_display(), venda.total])
        for item, desconto in zip(itens, descontos):
            receita = item.subtotal - desconto
            consumos = list(item.consumos_lote.all())
            custo = None if item.preco_custo is None else ((sum((c.quantidade * c.custo_unitario for c in consumos), ZERO)
                     if consumos else item.quantidade * item.preco_custo).quantize(CENTAVO, rounding=ROUND_HALF_UP))
            registro = produtos.setdefault(item.produto_id, {"produto": item.produto, "quantidade": ZERO,
                "receita": ZERO, "custo": ZERO, "sem_custo": 0})
            registro["quantidade"] += item.quantidade
            registro["receita"] += receita
            if custo is None:
                registro["sem_custo"] += 1
                sem_custo += 1
            else:
                registro["custo"] += custo
                lucro_conhecido += receita - custo
    ranking = sorted(produtos.values(), key=lambda r: r["receita"], reverse=True)
    for registro in ranking:
        registro["lucro"] = None if registro["sem_custo"] else registro["receita"] - registro["custo"]
    estoque, valor_estoque = [], ZERO
    for produto in Produto.objects.prefetch_related("lotes").all():
        if produto.controla_lote:
            valor = sum((l.quantidade * l.custo_unitario for l in produto.lotes.all()), ZERO)
        else:
            valor = produto.estoque_atual * produto.preco_custo
        valor = valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)
        valor_estoque += valor
        estoque.append({"produto": produto, "valor": valor})
    return {"vendas": linhas_vendas, "dias": sorted(dias.items()), "ranking": ranking, "estoque": estoque,
            "total_vendas": total, "qtd_vendas": len(linhas_vendas), "valor_estoque": valor_estoque,
            "lucro_conhecido": lucro_conhecido, "itens_sem_custo": sem_custo}


def tabela_exportacao(dados, tipo):
    if tipo == "produtos":
        return "Produtos mais vendidos e lucro", ["Produto", "Unidade", "Quantidade", "Receita líquida (R$)", "Custo (R$)", "Lucro bruto (R$)"], [
            [r["produto"].nome, r["produto"].unidade, r["quantidade"], r["receita"],
             None if r["sem_custo"] else r["custo"], r["lucro"]] for r in dados["ranking"]]
    if tipo == "estoque":
        return "Estoque valorizado atual", ["Produto", "Unidade", "Saldo físico", "Valor de custo (R$)"], [
            [r["produto"].nome, r["produto"].unidade, r["produto"].estoque_atual, r["valor"]] for r in dados["estoque"]]
    return "Vendas por período", ["Venda", "Data", "Cliente", "Pagamento", "Total (R$)"], dados["vendas"]


def celula_csv(valor):
    if valor is None:
        return "Custo não registrado"
    if isinstance(valor, Decimal):
        return format(valor, "f").replace(".", ",")
    texto = str(valor)
    if texto.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        texto = "'" + texto
    return texto


def exportar_csv(cabecalho, linhas):
    arquivo = StringIO(newline="")
    writer = csv.writer(arquivo, delimiter=";")
    writer.writerow(cabecalho)
    writer.writerows([[celula_csv(c) for c in linha] for linha in linhas])
    return ("\ufeff" + arquivo.getvalue()).encode("utf-8")


def exportar_pdf(titulo, cabecalho, linhas, periodo):
    import reportlab
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

    fontes = Path(reportlab.__file__).parent / "fonts"
    if "AgroVera" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("AgroVera", str(fontes / "Vera.ttf")))
        pdfmetrics.registerFont(TTFont("AgroVeraBold", str(fontes / "VeraBd.ttf")))
    estilo = ParagraphStyle("celula", fontName="AgroVera", fontSize=8, leading=11)
    titulo_estilo = ParagraphStyle("titulo", fontName="AgroVeraBold", fontSize=18, leading=24, textColor=colors.HexColor("#2f6b3a"))
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=38,
                             title=titulo, author=settings.NOME_LOJA)

    def texto(valor):
        if valor is None:
            return "Não registrado"
        if isinstance(valor, Decimal):
            return format(valor, "f").replace(".", ",")
        return str(valor)

    dados = [[Paragraph(escape(c), estilo) for c in cabecalho]]
    dados += [[Paragraph(escape(texto(c)), estilo) for c in linha] for linha in linhas]
    if not linhas:
        dados.append([Paragraph("Sem registros no período.", estilo)] + [""] * (len(cabecalho) - 1))
    largura = doc.width
    proporcoes = ([2.9, 0.6, 1, 1.4, 1.2, 1.3] if len(cabecalho) == 6 else
                  [3.5, 0.7, 1.2, 1.5] if len(cabecalho) == 4 else [0.6, 1.5, 2.5, 1.5, 1.1])
    tabela = LongTable(dados, colWidths=[largura * p / sum(proporcoes) for p in proporcoes], repeatRows=1)
    tabela.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f2ea")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8f5")]),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#2f6b3a")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    conteudo = [Paragraph(escape(settings.NOME_LOJA), titulo_estilo), Paragraph(escape(titulo), titulo_estilo),
                Paragraph(escape(periodo), estilo), Spacer(1, 12), tabela, Spacer(1, 12),
                Paragraph("Lucro bruto considera descontos e custo registrado na venda; não inclui despesas. "
                          "Custos ausentes em vendas antigas aparecem como não registrados. Estoque representa o saldo físico atual, inclusive lotes vencidos.", estilo)]

    def rodape(canvas, documento):
        canvas.setFont("AgroVera", 8)
        canvas.drawString(30, 20, timezone.localtime().strftime("Gerado em %d/%m/%Y %H:%M"))
        canvas.drawRightString(landscape(A4)[0] - 30, 20, f"Página {documento.page}")
    doc.build(conteudo, onFirstPage=rodape, onLaterPages=rodape)
    return buffer.getvalue()
