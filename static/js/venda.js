(function () {
  "use strict";
  var form = document.getElementById("form-venda");
  if (!form) return;
  var lista = document.getElementById("itens");
  var modelo = document.getElementById("modelo-item");
  var totalForms = document.getElementById("id_itens-TOTAL_FORMS");
  var busca = document.getElementById("busca-produto");
  var resultado = document.getElementById("resultado-busca");
  var moeda = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  var catalogo = new Map();
  var datalist = document.getElementById("catalogo-produtos");

  function num(v) { var n = Number(String(v || "0").replace(",", ".")); return Number.isFinite(n) ? n : 0; }
  function centavos(n) { return Math.round((n + Number.EPSILON) * 100); }
  function linhas() { return Array.from(lista.querySelectorAll("[data-item]")).filter(function (r) { return !r.hidden; }); }

  modelo.content.querySelectorAll("select[name$='-produto'] option").forEach(function (option) {
    if (!option.value) return;
    var produto = { id: option.value, nome: option.dataset.nome, codigo: option.dataset.codigo, preco: option.dataset.preco };
    produto.rotulo = produto.nome + " · " + (produto.codigo || "#" + produto.id);
    catalogo.set(produto.id, produto);
    var sugestao = document.createElement("option");
    sugestao.value = produto.rotulo;
    datalist.appendChild(sugestao);
  });

  function recalcular() {
    var soma = 0;
    linhas().forEach(function (linha) {
      var q = num(linha.querySelector("[name$='-quantidade']").value);
      var p = num(linha.querySelector("[name$='-preco_unitario']").value);
      var desconto = centavos(num(linha.querySelector("[name$='-desconto']").value));
      var subtotal = centavos(q * p) - desconto;
      linha.querySelector("[data-subtotal]").textContent = moeda.format(subtotal / 100);
      soma += subtotal;
    });
    soma -= centavos(num(document.getElementById("id_desconto").value));
    document.getElementById("total").textContent = moeda.format(soma / 100);
    var dividido = document.getElementById("id_forma_pagamento").value === "DIVIDIDO";
    var pago = 0;
    document.querySelectorAll(".parcela-pagamento").forEach(function (campo) {
      campo.hidden = !dividido;
      pago += centavos(num(campo.querySelector("input").value));
    });
    var conferencia = document.getElementById("conferencia-pagamento");
    conferencia.textContent = dividido ? "Pagamentos: " + moeda.format(pago / 100) + " · Diferença: " + moeda.format((soma - pago) / 100) : "";
    conferencia.classList.toggle("neg", dividido && pago !== soma);
  }

  function adicionar() {
    if (Number(totalForms.value) >= 100) {
      resultado.textContent = "Limite de 100 linhas por venda.";
      return null;
    }
    var tmp = document.createElement("div");
    tmp.innerHTML = modelo.innerHTML.replace(/__prefix__/g, totalForms.value).trim();
    var linha = tmp.firstElementChild;
    lista.appendChild(linha);
    totalForms.value = Number(totalForms.value) + 1;
    recalcular();
    return linha;
  }

  function adicionarBusca() {
    var texto = busca.value.trim().toLocaleLowerCase("pt-BR");
    if (!texto) { busca.focus(); return; }
    var exatos = Array.from(catalogo.values()).filter(function (p) {
      return (p.codigo && p.codigo.toLocaleLowerCase("pt-BR") === texto) || p.rotulo.toLocaleLowerCase("pt-BR") === texto;
    });
    var encontrados = exatos.length ? exatos : Array.from(catalogo.values()).filter(function (p) {
      return p.nome.toLocaleLowerCase("pt-BR").includes(texto);
    });
    if (encontrados.length !== 1) {
      resultado.textContent = encontrados.length ? "Escolha um produto nas sugestões para distinguir os resultados." : "Produto não encontrado. Confira o nome ou o código cadastrado.";
      return;
    }
    var produto = encontrados[0];
    var linha = linhas().find(function (r) { return r.querySelector("[name$='-produto']").value === produto.id; });
    if (linha) {
      var quantidade = linha.querySelector("[name$='-quantidade']");
      quantidade.value = String(Math.round((num(quantidade.value) + 1) * 1000) / 1000);
    } else {
      linha = linhas().find(function (r) { return !r.querySelector("[name$='-produto']").value; }) || adicionar();
      if (!linha) return;
      linha.querySelector("[name$='-produto']").value = produto.id;
      linha.querySelector("[name$='-quantidade']").value = "1";
      linha.querySelector("[name$='-preco_unitario']").value = produto.preco;
      linha.querySelector("[name$='-desconto']").value = "0";
    }
    busca.value = "";
    resultado.textContent = produto.nome + " adicionado à venda.";
    recalcular();
    busca.focus();
  }

  document.getElementById("adicionar-busca").addEventListener("click", adicionarBusca);
  busca.addEventListener("keydown", function (event) {
    if (event.key === "Enter") { event.preventDefault(); adicionarBusca(); }
  });
  document.getElementById("add-item").addEventListener("click", adicionar);
  lista.addEventListener("click", function (event) {
    if (!event.target.matches("[data-remover]")) return;
    var linha = event.target.closest("[data-item]");
    linha.querySelector("[name$='-DELETE']").checked = true;
    linha.hidden = true;
    if (!linhas().length) adicionar();
    recalcular();
  });
  lista.addEventListener("change", function (event) {
    if (event.target.matches("select[name$='-produto']")) {
      var option = event.target.selectedOptions[0];
      var linha = event.target.closest("[data-item]");
      if (option && option.dataset.preco) linha.querySelector("[name$='-preco_unitario']").value = option.dataset.preco;
      if (!linha.querySelector("[name$='-quantidade']").value) linha.querySelector("[name$='-quantidade']").value = "1";
    }
    recalcular();
  });
  form.addEventListener("input", recalcular);
  form.addEventListener("change", recalcular);
  form.addEventListener("submit", function () { form.querySelector("button[type='submit']").disabled = true; });
  window.addEventListener("pageshow", function () { form.querySelector("button[type='submit']").disabled = false; });
  lista.querySelectorAll("[data-item]").forEach(function (r) { r.hidden = r.querySelector("[name$='-DELETE']").checked; });
  recalcular();
})();
