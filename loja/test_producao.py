from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse

from scripts.backup_banco import ambiente_postgres
from .models import PerfilUsuario
from .tests import BaseTest


class ProducaoTest(BaseTest):
    @override_settings(AXES_ENABLED=True)
    def test_login_bloqueia_cinco_falhas_mesmo_trocando_user_agent(self):
        for n in range(5):
            response = self.client.post(reverse("login"), {"username": "gerente", "password": "incorreta"},
                                        HTTP_USER_AGENT=f"navegador-{n}")
        self.assertEqual(response.status_code, 429)
        response = self.client.post(reverse("login"), {"username": "gerente", "password": "x12345678"},
                                    REMOTE_ADDR="192.0.2.40")
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "temporariamente bloqueado", status_code=429)

    @override_settings(AXES_ENABLED=True)
    def test_login_correto_limpa_contador(self):
        for _ in range(4):
            self.client.post(reverse("login"), {"username": "func", "password": "incorreta"})
        response = self.client.post(reverse("login"), {"username": "func", "password": "x12345678"})
        self.assertEqual(response.status_code, 302)
        self.client.logout()
        for _ in range(4):
            response = self.client.post(reverse("login"), {"username": "func", "password": "incorreta"})
        self.assertEqual(response.status_code, 200)

    def test_senhas_fortes_e_frases_longas(self):
        for senha in ("abcdefghijk", "abcdefghijklmnop", "1234567890123456"):
            with self.assertRaises(ValidationError):
                validate_password(senha)
        validate_password("MinhaSenhaForte#2030")
        validate_password("o campo floresce ao amanhecer")

    def test_pwa_tem_icones_e_nao_cacheia_operacoes_privadas(self):
        manifesto = self.client.get(reverse("manifesto")).json()
        self.assertEqual(manifesto["display"], "standalone")
        self.assertEqual({i["sizes"] for i in manifesto["icons"]}, {"192x192", "512x512"})
        worker = self.client.get(reverse("service_worker"))
        self.assertContains(worker, 'request.method !== "GET"')
        self.assertNotContains(worker, '"/vendas/"')
        self.assertNotContains(worker, '"/clientes/"')
        self.assertEqual(worker["Service-Worker-Allowed"], "/")
        self.assertContains(self.client.get(reverse("offline")), "Sem conexão")

    def test_paginas_de_cliente_tem_cache_privado(self):
        self.client.force_login(self.func)
        response = self.client.get(reverse("cliente_lista"))
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])

    def test_gerente_cadastra_perfil_estoquista(self):
        self.client.force_login(self.gerente)
        response = self.client.post(reverse("usuario_novo"), {"username": "novoestoque", "first_name": "Estoque",
            "is_active": "on", "cargo": "ESTOQUISTA", "senha": "MinhaSenhaForte#2030", "confirmar_senha": "MinhaSenhaForte#2030"})
        self.assertEqual(response.status_code, 302)
        perfil = PerfilUsuario.objects.get(usuario__username="novoestoque")
        self.assertEqual(perfil.cargo, "ESTOQUISTA")
        self.assertFalse(perfil.usuario.is_staff)

    def test_backup_decodifica_senha_sem_alterar_uri_e_recusa_transaction_pooler(self):
        env = ambiente_postgres("postgresql://postgres.ref:teste%40seguro@aws.example.com:5432/postgres")
        self.assertEqual(env["PGPASSWORD"], "teste@seguro")
        self.assertEqual(env["PGSSLMODE"], "require")
        with self.assertRaises(ValueError):
            ambiente_postgres("postgresql://postgres:teste@aws.example.com:6543/postgres")
