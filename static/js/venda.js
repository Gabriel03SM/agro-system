(function () {
  var prefixo = "itens";
  var lista = document.getElementById("itens");
  var modelo = document.getElementById("modelo-item");
  var total = document.getElementById("total");
  var totalForms = document.getElementById("id_" + prefixo + "-TOTAL_FORMS");
  var moeda = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

  function num(v) {
    var n = parseFloat(String(v).replace(",", "."));
    return isNaN(n) ? 0 : n;
  }

  function recalcular() {
    var soma = 0;
    lista.querySelectorAll("[data-item]").forEach(function (linha) {
      var q = num(linha.querySelector('[name$="-quantidade"]').value);
      var p = num(linha.querySelector('[name$="-preco_unitario"]').value);
      var sub = Math.round(q * p * 100) / 100;
      linha.querySelector("[data-subtotal]").textContent = moeda.format(sub);
      soma += sub;
    });
    total.textContent = moeda.format(soma);
  }

  function renumerar() {
    var linhas = lista.querySelectorAll("[data-item]");
    linhas.forEach(function (linha, i) {
      linha.querySelectorAll("[name],[id]").forEach(function (el) {
        ["name", "id"].forEach(function (attr) {
          var v = el.getAttribute(attr);
          if (v) el.setAttribute(attr, v.replace(new RegExp(prefixo + "-(\\d+|__prefix__)-"), prefixo + "-" + i + "-"));
        });
      });
    });
    totalForms.value = linhas.length;
  }

  function adicionar() {
    var html = modelo.innerHTML.replace(/__prefix__/g, totalForms.value);
    var tmp = document.createElement("div");
    tmp.innerHTML = html.trim();
    lista.appendChild(tmp.firstElementChild);
    renumerar();
    recalcular();
  }

  document.getElementById("add-item").addEventListener("click", adicionar);

  lista.addEventListener("click", function (e) {
    if (!e.target.matches("[data-remover]")) return;
    if (lista.querySelectorAll("[data-item]").length <= 1) {
      // mantém ao menos uma linha: apenas limpa
      lista.querySelectorAll("input").forEach(function (i) { if (i.type !== "hidden") i.value = ""; });
      lista.querySelectorAll("select").forEach(function (s) { s.value = ""; });
    } else {
      e.target.closest("[data-item]").remove();
      renumerar();
    }
    recalcular();
  });

  lista.addEventListener("change", function (e) {
    if (e.target.matches('select[name$="-produto"]')) {
      var opt = e.target.options[e.target.selectedIndex];
      var linha = e.target.closest("[data-item]");
      var preco = linha.querySelector('[name$="-preco_unitario"]');
      if (opt && opt.dataset.preco) preco.value = opt.dataset.preco;
      var qtd = linha.querySelector('[name$="-quantidade"]');
      if (!qtd.value) qtd.value = "1";
    }
    recalcular();
  });
  lista.addEventListener("input", recalcular);

  recalcular();
})();
