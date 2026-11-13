(function () {
  "use strict";
  var toggle = document.getElementById("abrir-menu");
  var menu = document.getElementById("menu-principal");
  if (toggle && menu) toggle.addEventListener("click", function () {
    var aberto = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(aberto));
    menu.classList.toggle("aberto", aberto);
  });
  var instalar = document.getElementById("instalar-app");
  var convite;
  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault(); convite = event;
    if (instalar) instalar.hidden = false;
  });
  if (instalar) instalar.addEventListener("click", async function () {
    if (!convite) return;
    await convite.prompt(); convite = null; instalar.hidden = true;
  });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/service-worker.js").catch(function () {});
})();
