"""Fluxos reais no navegador, sempre contra banco temporário e servidor local."""
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
SAIDA = ROOT / "tmp" / "browser"
SAIDA.mkdir(parents=True, exist_ok=True)
SENHA = "SenhaApenasDeTeste#2030"


def login(page, base, usuario="gerente_teste"):
    page.goto(base + "/entrar/")
    page.get_by_label("Usuário", exact=True).fill(usuario)
    page.get_by_label("Senha", exact=True).fill(SENHA)
    page.get_by_role("button", name="Entrar", exact=True).click()
    page.wait_for_url(re.compile(r"/(?:lotes/)?$"))


def main():
    with tempfile.TemporaryDirectory(prefix="agro-browser-") as tmp:
        env = os.environ.copy()
        env.update(DJANGO_SETTINGS_MODULE="config.test_settings", TEST_DB_PATH=str(Path(tmp) / "teste.sqlite3"),
                   TEST_DATABASE_URL="", DEBUG="True", SECRET_KEY="browser-test-only", PYTHONIOENCODING="utf-8")
        subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], cwd=ROOT, env=env, check=True,
                       stdout=subprocess.DEVNULL)
        seed = '''import django; django.setup()
from django.contrib.auth import get_user_model
from loja.models import Produto, Fornecedor, PerfilUsuario
u=get_user_model().objects.create_user("gerente_teste", password="SenhaApenasDeTeste#2030", is_staff=True)
e=get_user_model().objects.create_user("estoquista_teste", password="SenhaApenasDeTeste#2030")
PerfilUsuario.objects.create(usuario=e, cargo="ESTOQUISTA")
Produto.objects.create(nome="Ração 25kg", codigo="789000000001", preco_venda=100, preco_custo=70, estoque_atual=20)
Produto.objects.create(nome="Semente", codigo="789000000002", preco_venda=10, preco_custo=5, estoque_atual=20)
Fornecedor.objects.create(nome="Distribuidora Teste")
'''
        subprocess.run([sys.executable, "-c", seed], cwd=ROOT, env=env, check=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            porta = sock.getsockname()[1]
        base = f"http://127.0.0.1:{porta}"
        with open(Path(tmp) / "servidor.log", "w", encoding="utf-8") as log:
            server = subprocess.Popen([sys.executable, "manage.py", "runserver", f"127.0.0.1:{porta}", "--noreload"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                for _ in range(100):
                    try:
                        with urlopen(base + "/healthz", timeout=1):
                            break
                    except Exception:
                        if server.poll() is not None:
                            raise RuntimeError("O servidor de teste encerrou antes de iniciar.")
                        time.sleep(0.3)
                else:
                    raise RuntimeError("O servidor de teste não iniciou.")
                with sync_playwright() as p:
                    options = {"headless": True}
                    if os.environ.get("E2E_BROWSER_CHANNEL"):
                        options["channel"] = os.environ["E2E_BROWSER_CHANNEL"]
                    browser = p.chromium.launch(**options)
                    try:
                        context = browser.new_context(viewport={"width": 1440, "height": 1000})
                        page = context.new_page()
                        erros = []
                        page.on("pageerror", lambda erro: erros.append(str(erro)))
                        login(page, base)
                        page.goto(base + "/caixa/abrir/")
                        page.get_by_label("Troco inicial em dinheiro (R$)").fill("50")
                        page.get_by_role("button", name="Salvar", exact=True).click()
                        page.wait_for_url(base + "/caixa/")

                        page.goto(base + "/vendas/nova/")
                        busca = page.get_by_label("Digite o produto ou leia o código de barras")
                        for _ in range(2):
                            busca.fill("789000000001")
                            busca.press("Enter")
                        expect(page.locator('[name="itens-0-quantidade"]')).to_have_value("2")
                        page.locator('[name="itens-0-desconto"]').fill("10")
                        page.get_by_label("Desconto na venda (R$)", exact=True).fill("5")
                        page.get_by_label("Forma de pagamento", exact=True).select_option("DIVIDIDO")
                        page.get_by_label("Dinheiro (R$)", exact=True).fill("85")
                        page.get_by_label("Pix (R$)", exact=True).fill("100")
                        expect(page.locator("#total")).to_contain_text("185,00")
                        page.screenshot(path=str(SAIDA / "venda-desktop.png"), full_page=True)
                        page.get_by_role("button", name="Registrar venda", exact=True).click()
                        page.wait_for_url(re.compile(r"/vendas/\d+/$"))
                        venda_url = page.url
                        expect(page.get_by_role("link", name="Imprimir comprovante")).to_be_visible()
                        page.get_by_role("link", name="Corrigir venda", exact=True).click()
                        page.locator('[name="itens-0-quantidade"]').fill("3")
                        page.get_by_label("Pix (R$)", exact=True).fill("200")
                        page.get_by_label("Motivo da correção").fill("Conferência do pedido")
                        page.get_by_role("button", name="Salvar correção", exact=True).click()
                        page.wait_for_url(venda_url)
                        expect(page.locator("tfoot")).to_contain_text("285,00")

                        page.goto(base + "/clientes/novo/")
                        page.get_by_label("Nome", exact=True).fill("Ana Teste")
                        page.get_by_role("button", name="Salvar", exact=True).click()
                        page.wait_for_url(re.compile(r"/clientes/\d+/$"))
                        cliente_url = page.url
                        cliente_id = cliente_url.rstrip("/").rsplit("/", 1)[1]
                        page.goto(base + "/vendas/nova/")
                        page.get_by_label("Digite o produto ou leia o código de barras").fill("789000000001")
                        page.get_by_label("Digite o produto ou leia o código de barras").press("Enter")
                        page.get_by_label("Cliente cadastrado", exact=True).select_option(cliente_id)
                        page.get_by_label("Forma de pagamento", exact=True).select_option("FIADO")
                        page.get_by_role("button", name="Registrar venda", exact=True).click()
                        page.wait_for_url(re.compile(r"/vendas/\d+/$"))
                        page.goto(cliente_url)
                        page.get_by_label("Valor recebido (R$)").fill("40")
                        page.get_by_label("Forma de recebimento", exact=True).select_option("PIX")
                        page.get_by_role("button", name="Registrar recebimento", exact=True).click()
                        expect(page.locator(".linha").filter(has_text="Saldo devedor")).to_contain_text("60,00")
                        page.screenshot(path=str(SAIDA / "cliente-fiado.png"), full_page=True)

                        page.goto(base + "/contas/nova/")
                        page.get_by_label("Descrição", exact=True).fill("Compra de mercadoria")
                        page.get_by_label("Valor total (R$)", exact=True).fill("150")
                        page.get_by_label("Vencimento", exact=True).fill("2030-12-31")
                        page.get_by_role("button", name="Salvar", exact=True).click()
                        page.wait_for_url(re.compile(r"/contas/\d+/$"))
                        page.get_by_label("Valor pago (R$)", exact=True).fill("50")
                        page.get_by_label("Forma de pagamento", exact=True).select_option("PIX")
                        page.get_by_role("button", name="Registrar pagamento", exact=True).click()
                        expect(page.locator(".linha").filter(has_text="Saldo a pagar")).to_contain_text("100,00")

                        page.goto(base + "/relatorios/")
                        expect(page.get_by_role("heading", name="Relatórios", exact=True)).to_be_visible()
                        page.screenshot(path=str(SAIDA / "relatorios.png"), full_page=True)
                        with page.expect_download() as download:
                            page.get_by_role("link", name="CSV", exact=True).first.click()
                        assert Path(download.value.path()).read_bytes().startswith(b"\xef\xbb\xbf")
                        with page.expect_download() as download:
                            page.get_by_role("link", name="PDF", exact=True).first.click()
                        assert Path(download.value.path()).read_bytes().startswith(b"%PDF-")

                        stock_context = browser.new_context()
                        stock_page = stock_context.new_page()
                        login(stock_page, base, "estoquista_teste")
                        assert stock_page.goto(base + "/caixa/").status == 403
                        stock_context.close()

                        mobile = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
                        mp = mobile.new_page()
                        login(mp, base)
                        mp.goto(base + "/vendas/nova/")
                        mp.get_by_role("button", name="Menu", exact=True).click()
                        expect(mp.get_by_role("navigation")).to_be_visible()
                        mp.get_by_role("button", name="Menu", exact=True).click()
                        assert mp.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "A tela móvel tem rolagem horizontal."
                        mp.screenshot(path=str(SAIDA / "venda-mobile.png"), full_page=True)
                        mp.get_by_label("Digite o produto ou leia o código de barras").fill("racao")
                        mp.get_by_label("Digite o produto ou leia o código de barras").press("Enter")
                        expect(mp.locator('[name="itens-0-produto"]')).to_have_value("1")
                        mp.evaluate("navigator.serviceWorker.ready")
                        mobile.set_offline(True)
                        mp.goto(base + "/produtos/")
                        expect(mp.get_by_role("heading", name="Sem conexão")).to_be_visible()
                        mobile.set_offline(False)
                        mobile.close()
                        assert not erros, erros
                        print("Navegador: venda, código de barras, descontos, pagamento dividido, correção, fiado, contas, exportações, perfis, tela móvel e PWA offline passaram.")
                    finally:
                        browser.close()
            finally:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                else:
                    server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)


if __name__ == "__main__":
    main()
