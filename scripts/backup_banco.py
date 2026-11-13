"""Exporta as tabelas Django, testa a restauração e grava somente o arquivo cifrado.

Requer pg_dump/pg_restore/psql e age no PATH. Credenciais vêm apenas do ambiente.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urlsplit


def ambiente_postgres(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname or not parsed.username:
        raise ValueError("Configure uma URL PostgreSQL válida no ambiente.")
    if parsed.port == 6543:
        raise ValueError("Use conexão direta ou Session pooler (5432), não Transaction pooler (6543).")
    if not parsed.path.strip("/"):
        raise ValueError("A URL deve identificar o banco.")
    env = os.environ.copy()
    env.update(PGHOST=parsed.hostname, PGPORT=str(parsed.port or 5432), PGUSER=unquote(parsed.username),
               PGPASSWORD=unquote(parsed.password or ""), PGDATABASE=unquote(parsed.path.lstrip("/")),
               PGSSLMODE=parse_qs(parsed.query).get("sslmode", ["require"])[0], PGCONNECT_TIMEOUT="20")
    return env


def executar(comando, env):
    # Não imprime parâmetros de conexão nem stderr contendo dados do banco.
    result = subprocess.run(comando, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError(f"A etapa {Path(comando[0]).name} falhou (código {result.returncode}). Confira acesso, versões e permissões.")
    return result.stdout


def backup(destino):
    fonte = os.environ.get("BACKUP_DATABASE_URL", "")
    recipiente = os.environ.get("BACKUP_AGE_RECIPIENT", "").strip()
    teste = os.environ.get("RESTORE_TEST_DATABASE_URL", "")
    if not fonte or not recipiente or not teste:
        raise ValueError("Configure BACKUP_DATABASE_URL, BACKUP_AGE_RECIPIENT e RESTORE_TEST_DATABASE_URL.")
    if not recipiente.startswith("age1") or any(c.isspace() for c in recipiente):
        raise ValueError("BACKUP_AGE_RECIPIENT deve conter uma chave pública age válida.")
    for binario in ("pg_dump", "pg_restore", "psql", "age"):
        if not shutil.which(binario):
            raise ValueError(f"Instale {binario} antes de executar o backup.")
    origem_env, teste_env = ambiente_postgres(fonte), ambiente_postgres(teste)
    # A restauração é permitida exclusivamente em um serviço local/efêmero de teste.
    if teste_env["PGHOST"] not in ("localhost", "127.0.0.1", "postgres", "scratch"):
        raise ValueError("O teste de restauração deve usar PostgreSQL local/efêmero, nunca um servidor de produção.")
    identificador = lambda e: (e["PGHOST"], e["PGPORT"], e["PGDATABASE"])
    if identificador(origem_env) == identificador(teste_env):
        raise ValueError("O banco de teste deve ser diferente da origem do backup.")
    destino = Path(destino).resolve()
    destino.mkdir(parents=True, exist_ok=True)
    nome = datetime.now(timezone.utc).strftime("agro-%Y%m%dT%H%M%SZ.dump.age")
    arquivo = destino / nome
    if arquivo.exists():
        raise ValueError("Já existe um backup com esse horário. Tente novamente em um segundo.")
    try:
        with tempfile.TemporaryDirectory(prefix="agro-backup-") as temporario:
            bruto = Path(temporario) / "banco.dump"
            comando = ["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--file", str(bruto)]
            for padrao in ("public.loja_*", "public.auth_*", "public.django_*", "public.axes_*"):
                comando += ["--table", padrao]
            executar(comando, origem_env)
            lista = executar(["pg_restore", "--list", str(bruto)], origem_env)
            if b"loja_venda" not in lista or b"auth_user" not in lista:
                raise RuntimeError("O arquivo não contém as tabelas essenciais do Agro Gestão.")
            executar(["pg_restore", "--exit-on-error", "--single-transaction", "--no-owner", "--no-acl",
                      "--dbname", teste_env["PGDATABASE"], str(bruto)], teste_env)
            resultado = executar(["psql", "--no-psqlrc", "--tuples-only", "--command",
                "SELECT count(*) FROM public.loja_venda;"], teste_env)
            if not resultado.strip().isdigit():
                raise RuntimeError("Não foi possível consultar o banco restaurado.")
            executar(["age", "--recipient", recipiente, "--output", str(arquivo), str(bruto)], origem_env)
        digest = hashlib.sha256(arquivo.read_bytes()).hexdigest()
        arquivo.with_suffix(arquivo.suffix + ".sha256").write_text(f"{digest}  {arquivo.name}\n", encoding="ascii")
    except Exception:
        arquivo.unlink(missing_ok=True)
        raise
    print(f"Backup cifrado e restauração de teste concluídos: {arquivo.name}")
    return arquivo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destino", default="backups")
    args = parser.parse_args()
    try:
        backup(args.destino)
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
