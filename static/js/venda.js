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
  function normalizar(s) { return String(s).toLocaleLowerCase("pt-BR").normalize("NFD").replace(/[\u0300-\u036f]/g, ""); }
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

  var preparados = new WeakSet();

  function candidatos(texto) {
    var termo = normalizar(texto.trim());
    if (!termo) return [];
    var produtos = Array.from(catalogo.values());
    var exatos = produtos.filter(function (p) {
      return (p.codigo && normalizar(p.codigo) === termo) || normalizar(p.rotulo) === termo;
    });
    return exatos.length ? exatos : produtos.filter(function (p) { return normalizar(p.nome).includes(termo); });
  }

  function atualizarBuscaDaLinha(linha) {
    var select = linha.querySelector("select[name$='-produto']");
    var campo = linha.querySelector("[data-produto-busca]");
    if (!campo) return;
    var produto = catalogo.get(select.value);
    var opcao = select.selectedOptions[0];
    campo.value = produto ? produto.rotulo : (opcao && opcao.dataset.nome ? opcao.dataset.nome : "");
  }

  function prepararLinha(linha) {
    var select = linha.querySelector("select[name$='-produto']");
    if (!select || preparados.has(select)) return;
    preparados.add(select);
    var campo = document.createElement("input");
    campo.type = "search";
    campo.id = select.id + "-busca";
    campo.className = "produto-busca-linha";
    campo.dataset.produtoBusca = "";
    campo.setAttribute("list", "catalogo-produtos");
    campo.setAttribute("autocomplete", "off");
    campo.setAttribute("aria-label", "Produto");
    campo.placeholder = "Digite para buscar";
    if (select.required) campo.setAttribute("aria-required", "true");
    ["aria-describedby", "aria-invalid"].forEach(function (atributo) {
      if (select.hasAttribute(atributo)) campo.setAttribute(atributo, select.getAttribute(atributo));
    });
    select.insertAdjacentElement("afterend", campo);
    var rotulo = select.closest(".campo").querySelector("label");
    if (rotulo) rotulo.htmlFor = campo.id;
    select.classList.add("produto-nativo");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    atualizarBuscaDaLinha(linha);

    function selecionar() {
      var encontrados = candidatos(campo.value);
      if (encontrados.length !== 1) {
        select.value = "";
        campo.setAttribute("aria-invalid", "true");
        resultado.textContent = encontrados.length ? "Escolha um produto nas sugestões." : "Produto não encontrado. Confira o nome ou o código.";
        return false;
      }
      select.value = encontrados[0].id;
      campo.removeAttribute("aria-invalid");
      select.dispatchEvent(new Event("change", { bubbles: true }));
      atualizarBuscaDaLinha(linha);
      return true;
    }
    campo.addEventListener("input", function () {
      select.value = "";
      campo.removeAttribute("aria-invalid");
    });
    campo.addEventListener("change", selecionar);
    campo.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" || event.isComposing) return;
      event.preventDefault();
      if (selecionar()) linha.querySelector("[name$='-quantidade']").focus();
    });
  }

  function focarProduto(linha) {
    var campo = linha && (linha.querySelector("[data-produto-busca]") || linha.querySelector("select[name$='-produto']"));
    if (campo) campo.focus();
  }

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
    prepararLinha(linha);
    totalForms.value = Number(totalForms.value) + 1;
    recalcular();
    return linha;
  }

  function adicionarBusca() {
    var texto = normalizar(busca.value.trim());
    if (!texto) { busca.focus(); return; }
    var exatos = Array.from(catalogo.values()).filter(function (p) {
      return (p.codigo && normalizar(p.codigo) === texto) || normalizar(p.rotulo) === texto;
    });
    var encontrados = exatos.length ? exatos : Array.from(catalogo.values()).filter(function (p) {
      return normalizar(p.nome).includes(texto);
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
    atualizarBuscaDaLinha(linha);
    busca.value = "";
    resultado.textContent = produto.nome + " adicionado à venda.";
    recalcular();
    busca.focus();
  }

  document.getElementById("adicionar-busca").addEventListener("click", adicionarBusca);
  busca.addEventListener("keydown", function (event) {
    if (event.key === "Enter") { event.preventDefault(); adicionarBusca(); }
  });
  document.getElementById("add-item").addEventListener("click", function () { focarProduto(adicionar()); });
  lista.addEventListener("click", function (event) {
    var botao = event.target.closest("[data-remover]");
    if (!botao) return;
    var linha = botao.closest("[data-item]");
    linha.querySelector("[name$='-DELETE']").checked = true;
    linha.hidden = true;
    if (!linhas().length) adicionar();
    recalcular();
    busca.focus();
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
  lista.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" || event.isComposing || event.ctrlKey || event.metaKey) return;
    if (!event.target.matches("[name$='-quantidade'],[name$='-preco_unitario'],[name$='-desconto']")) return;
    event.preventDefault();
    var atual = event.target.closest("[data-item]");
    if (!atual.querySelector("[name$='-produto']").value) focarProduto(atual);
    else focarProduto(adicionar());
  });
  form.addEventListener("input", recalcular);
  form.addEventListener("change", recalcular);
  form.addEventListener("submit", function () { form.querySelector("button[type='submit']").disabled = true; });
  window.addEventListener("pageshow", function () { form.querySelector("button[type='submit']").disabled = false; });
  lista.querySelectorAll("[data-item]").forEach(function (r) {
    r.hidden = r.querySelector("[name$='-DELETE']").checked;
    prepararLinha(r);
  });
  recalcular();
  if (!form.querySelector(".campo-com-erro,[aria-invalid='true']")) busca.focus({ preventScroll: true });
})();
