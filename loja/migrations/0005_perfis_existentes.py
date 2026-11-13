from django.conf import settings
from django.db import migrations


def criar_perfis(apps, schema_editor):
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    Usuario = apps.get_model(app_label, model_name)
    Perfil = apps.get_model("loja", "PerfilUsuario")
    alias = schema_editor.connection.alias
    for usuario in Usuario.objects.using(alias).all().iterator():
        Perfil.objects.using(alias).get_or_create(usuario_id=usuario.pk,
            defaults={"cargo": "GERENTE" if usuario.is_staff or usuario.is_superuser else "CAIXA"})


class Migration(migrations.Migration):
    dependencies = [("loja", "0004_gestao_lotes_contas_perfis"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.RunPython(criar_perfis, migrations.RunPython.noop)]
