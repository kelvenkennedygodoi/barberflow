from django.db import migrations


def normalizar_telefones(apps, schema_editor):
    Cliente = apps.get_model("gestao", "Cliente")
    for cliente in Cliente.objects.exclude(telefone="").iterator():
        normalizado = "".join(
            caractere for caractere in cliente.telefone if caractere.isdigit()
        )
        if not normalizado or normalizado == cliente.telefone:
            continue
        duplicado = Cliente.objects.filter(
            barbearia_id=cliente.barbearia_id,
            telefone=normalizado,
        ).exclude(pk=cliente.pk)
        if not duplicado.exists():
            Cliente.objects.filter(pk=cliente.pk).update(telefone=normalizado)


class Migration(migrations.Migration):
    dependencies = [("gestao", "0002_agendamento_origem_bloqueioagenda_horariotrabalho")]

    operations = [migrations.RunPython(normalizar_telefones, migrations.RunPython.noop)]
