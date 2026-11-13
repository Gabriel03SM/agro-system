from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = (
        "Ativa Row Level Security em todas as tabelas do schema public (Supabase). "
        "Impede acesso às tabelas pela API pública do Supabase; o Django continua funcionando normalmente."
    )

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write("Banco não é PostgreSQL; nada a fazer.")
            return
        with connection.cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            tabelas = [r[0] for r in cur.fetchall()]
            ok = 0
            for t in tabelas:
                try:
                    cur.execute(f"ALTER TABLE public.{connection.ops.quote_name(t)} ENABLE ROW LEVEL SECURITY")
                    ok += 1
                except Exception as exc:  # tabela de outra extensão, sem permissão etc.
                    self.stderr.write(f"Aviso: não foi possível ativar RLS em {t}: {exc}")
        self.stdout.write(self.style.SUCCESS(f"RLS ativado em {ok} tabela(s)."))
