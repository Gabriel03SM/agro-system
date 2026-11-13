(function () {
  "use strict";
  var toggle = document.getElementById("abrir-menu");
  var menu = document.getElementById("menu-principal");
  function fecharMenu(devolverFoco) {
    if (!menu || !toggle) return;
    menu.classList.remove("aberto");
    toggle.setAttribute("aria-expanded", "false");
    if (devolverFoco) toggle.focus();
  }
  if (toggle && menu) {
    toggle.addEventListener("click", function () {
      var aberto = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", String(aberto));
      menu.classList.toggle("aberto", aberto);
      if (aberto) {
        var primeiro = menu.querySelector("a");
        if (primeiro) primeiro.focus();
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && menu.classList.contains("aberto")) fecharMenu(true);
    });
    document.addEventListener("click", function (event) {
      if (menu.classList.contains("aberto") && !menu.contains(event.target) && !toggle.contains(event.target)) fecharMenu(false);
    });
    menu.addEventListener("click", function (event) {
      if (event.target.closest("a")) fecharMenu(false);
    });
    window.matchMedia("(min-width: 1024px)").addEventListener("change", function (event) {
      if (event.matches) fecharMenu(false);
    });
  }

  document.querySelectorAll(".campo").forEach(function (campo) {
    var controle = campo.querySelector("input:not([type='hidden']),select,textarea");
    if (!controle) return;
    var referencias = (controle.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
    campo.querySelectorAll(".ajuda-campo[id],.erros-campo[id]").forEach(function (texto) {
      if (!referencias.includes(texto.id)) referencias.push(texto.id);
    });
    if (referencias.length) controle.setAttribute("aria-describedby", referencias.join(" "));
    if (campo.classList.contains("campo-com-erro")) controle.setAttribute("aria-invalid", "true");
  });
  document.querySelectorAll("table thead th").forEach(function (cabecalho) {
    if (!cabecalho.hasAttribute("scope")) cabecalho.setAttribute("scope", "col");
  });
  var primeiroErro = document.querySelector(".campo-com-erro input:not([type='hidden']):not(.produto-nativo),.campo-com-erro select:not(.produto-nativo),.campo-com-erro textarea");
  if (primeiroErro) primeiroErro.focus();

  function dispensar(aviso) {
    aviso.hidden = true;
    var grupo = aviso.closest(".mensagens");
    if (grupo && !grupo.querySelector(".aviso:not([hidden])")) grupo.hidden = true;
  }
  document.querySelectorAll("[data-dispensar]").forEach(function (botao) {
    botao.addEventListener("click", function () { dispensar(botao.closest(".aviso")); });
  });
  document.querySelectorAll("[data-sucesso]").forEach(function (aviso) {
    var timer;
    function agendar() {
      clearTimeout(timer);
      timer = setTimeout(function () {
        if (aviso.matches(":hover") || aviso.contains(document.activeElement)) agendar();
        else dispensar(aviso);
      }, 7000);
    }
    aviso.addEventListener("mouseenter", function () { clearTimeout(timer); });
    aviso.addEventListener("mouseleave", agendar);
    aviso.addEventListener("focusin", function () { clearTimeout(timer); });
    aviso.addEventListener("focusout", agendar);
    agendar();
  });

  var dialogo = document.getElementById("confirmacao");
  var operacao;
  var autorizados = new WeakSet();
  document.addEventListener("submit", function (event) {
    var formulario = event.target;
    if (!(formulario instanceof HTMLFormElement) || !formulario.dataset.confirm) return;
    if (autorizados.has(formulario)) { autorizados.delete(formulario); return; }
    if (!dialogo || typeof dialogo.showModal !== "function") {
      if (!window.confirm(formulario.dataset.confirm)) event.preventDefault();
      return;
    }
    event.preventDefault();
    operacao = { formulario: formulario, botao: event.submitter, foco: document.activeElement };
    document.getElementById("confirmacao-titulo").textContent = formulario.dataset.confirmTitulo || "Confirmar ação";
    document.getElementById("confirmacao-texto").textContent = formulario.dataset.confirm;
    document.getElementById("confirmacao-executar").textContent = formulario.dataset.confirmBotao || "Confirmar";
    dialogo.returnValue = "";
    document.body.classList.add("modal-aberto");
    dialogo.showModal();
    document.getElementById("confirmacao-cancelar").focus();
  }, true);
  if (dialogo) {
    dialogo.addEventListener("close", function () {
      document.body.classList.remove("modal-aberto");
      var atual = operacao;
      operacao = null;
      if (!atual) return;
      if (dialogo.returnValue === "confirmar") {
        autorizados.add(atual.formulario);
        if (typeof atual.formulario.requestSubmit === "function") {
          if (atual.botao && atual.botao.isConnected) atual.formulario.requestSubmit(atual.botao);
          else atual.formulario.requestSubmit();
        } else HTMLFormElement.prototype.submit.call(atual.formulario);
      } else if (atual.foco && atual.foco.isConnected) atual.foco.focus();
    });
    dialogo.addEventListener("click", function (event) {
      if (event.target !== dialogo) return;
      var limites = dialogo.getBoundingClientRect();
      if (event.clientX < limites.left || event.clientX > limites.right || event.clientY < limites.top || event.clientY > limites.bottom) dialogo.close("cancelar");
    });
  }

  var instalar = document.getElementById("instalar-app");
  var convite;
  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    convite = event;
    if (instalar) instalar.hidden = false;
  });
  if (instalar) instalar.addEventListener("click", async function () {
    if (!convite) return;
    await convite.prompt();
    convite = null;
    instalar.hidden = true;
  });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/service-worker.js").catch(function () {});
})();
