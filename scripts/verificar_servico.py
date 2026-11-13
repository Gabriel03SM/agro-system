"""Verificação pública de aplicação e banco, sem credenciais."""
import argparse
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def verificar(url, tentativas=3):
    origem = urlsplit(url)
    if origem.scheme != "https" or not origem.hostname or origem.username or origem.password or origem.query or origem.fragment:
        raise ValueError("Informe uma URL HTTPS pública, sem credenciais ou parâmetros.")
    destino = url.rstrip("/") + "/readyz"
    for tentativa in range(tentativas):
        try:
            with urlopen(Request(destino, headers={"User-Agent": "AgroGestao-HealthCheck/1.0"}), timeout=90) as response:
                if response.status == 200 and response.read(32).strip() == b"ok":
                    print(f"Aplicação e banco respondendo em {origem.hostname}.")
                    return True
        except (HTTPError, URLError, TimeoutError):
            pass
        if tentativa + 1 < tentativas:
            time.sleep(15)
    print(f"Falha na verificação de {origem.hostname} após {tentativas} tentativas.")
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("PUBLIC_SITE_URL", "https://agro-gestao.onrender.com"))
    args = parser.parse_args()
    try:
        raise SystemExit(0 if verificar(args.url) else 1)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
