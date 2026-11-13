from django.core.exceptions import ValidationError


class DiversidadeSenhaValidator:
    def validate(self, password, user=None):
        grupos = [any(c.islower() for c in password), any(c.isupper() for c in password),
                  any(c.isdigit() for c in password), any(not c.isalnum() for c in password)]
        if len(password) >= 20 and any(c.isspace() for c in password) and any(c.isalpha() for c in password):
            return
        if sum(grupos) < 3:
            raise ValidationError("Use ao menos três tipos: minúsculas, maiúsculas, números e símbolos; "
                                  "ou uma frase com pelo menos 20 caracteres.", code="senha_pouco_variada")

    def get_help_text(self):
        return "Use três tipos de caracteres ou uma frase com pelo menos 20 caracteres."
