import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Cria o superusuário a partir das variáveis DJANGO_SUPERUSER_* (se ainda não existir nenhum)."

    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write("Já existe um superusuário; nada a fazer.")
            return
        usuario = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        senha = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
        if not usuario or not senha:
            self.stdout.write("DJANGO_SUPERUSER_USERNAME/PASSWORD não definidos; pulando.")
            return
        User.objects.create_superuser(username=usuario, email=email, password=senha)
        self.stdout.write(self.style.SUCCESS(f"Superusuário '{usuario}' criado."))
