import uuid

from django.db import migrations, models


def preencher_tokens(apps, schema_editor):
    Agendamento = apps.get_model("gestao", "Agendamento")
    for agendamento in Agendamento.objects.filter(token_publico__isnull=True).iterator():
        agendamento.token_publico = uuid.uuid4()
        agendamento.save(update_fields=["token_publico"])


class Migration(migrations.Migration):
    dependencies = [("gestao", "0006_cliente_aceita_notificacoes_whatsapp_and_more")]

    operations = [
        migrations.AddField(model_name="barbearia", name="descricao_publica", field=models.TextField(blank=True)),
        migrations.AddField(model_name="barbearia", name="logo_url", field=models.URLField(blank=True)),
        migrations.AddField(model_name="barbearia", name="mapa_url", field=models.URLField(blank=True)),
        migrations.AddField(model_name="barbearia", name="instagram", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="barbearia", name="horario_funcionamento", field=models.TextField(blank=True)),
        migrations.AddField(model_name="barbearia", name="politica_cancelamento", field=models.TextField(blank=True)),
        migrations.AddField(model_name="barbearia", name="politica_privacidade", field=models.TextField(blank=True)),
        migrations.AddField(model_name="barbearia", name="antecedencia_agendamento_minutos", field=models.PositiveSmallIntegerField(default=30)),
        migrations.AddField(model_name="barbearia", name="limite_agendamento_dias", field=models.PositiveSmallIntegerField(default=60)),
        migrations.AddField(model_name="barbearia", name="intervalo_agendamento_minutos", field=models.PositiveSmallIntegerField(default=15)),
        migrations.AddField(model_name="barbearia", name="antecedencia_cancelamento_horas", field=models.PositiveSmallIntegerField(default=2)),
        migrations.AddField(model_name="usuario", name="especialidades", field=models.CharField(blank=True, max_length=180)),
        migrations.AddField(model_name="usuario", name="foto_url", field=models.URLField(blank=True)),
        migrations.AddField(model_name="agendamento", name="token_publico", field=models.UUIDField(editable=False, null=True)),
        migrations.RunPython(preencher_tokens, migrations.RunPython.noop),
        migrations.AlterField(model_name="agendamento", name="token_publico", field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
    ]
