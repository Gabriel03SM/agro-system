from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.db import transaction

from .auditoria import com_usuario
from .models import PerfilUsuario
from .permissoes import cargo_usuario
from .services import RegraNegocio


class UsuarioForm(forms.ModelForm):
    cargo = forms.ChoiceField(label="Perfil", choices=PerfilUsuario.CARGOS)
    senha = forms.CharField(label="Nova senha", widget=forms.PasswordInput, required=False,
                            help_text="Obrigatória no cadastro. Ao editar, deixe vazia para manter a senha.")
    confirmar_senha = forms.CharField(label="Confirmar senha", widget=forms.PasswordInput, required=False)

    class Meta:
        model = get_user_model()
        fields = ["username", "first_name", "email", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["cargo"].initial = cargo_usuario(self.instance)

    def clean(self):
        dados = super().clean()
        senha = dados.get("senha")
        if not self.instance.pk and not senha:
            self.add_error("senha", "Informe uma senha para o novo usuário.")
        if senha != dados.get("confirmar_senha"):
            self.add_error("confirmar_senha", "As senhas não conferem.")
        if senha:
            candidato = get_user_model()(username=dados.get("username", ""), email=dados.get("email", ""))
            try:
                password_validation.validate_password(senha, candidato)
            except ValidationError as exc:
                self.add_error("senha", exc)
        return dados


@transaction.atomic
@com_usuario
def salvar_usuario(form, usuario):
    if cargo_usuario(usuario) != "GERENTE":
        raise RegraNegocio("Somente um gerente pode gerenciar usuários.")
    alvo = form.save(commit=False)
    cargo = form.cleaned_data["cargo"]
    if alvo.pk == usuario.pk and (not alvo.is_active or cargo != "GERENTE"):
        raise RegraNegocio("Você não pode desativar ou retirar seu próprio perfil de gerente.")
    if alvo.is_superuser and cargo != "GERENTE":
        raise RegraNegocio("O administrador principal deve manter o perfil de gerente.")
    alvo.is_staff = cargo == "GERENTE"
    if form.cleaned_data.get("senha"):
        alvo.set_password(form.cleaned_data["senha"])
    alvo.save()
    PerfilUsuario.objects.update_or_create(usuario=alvo, defaults={"cargo": cargo})
    return alvo
