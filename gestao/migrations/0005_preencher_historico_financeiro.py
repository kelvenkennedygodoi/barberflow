from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations


def preencher_historico_financeiro(apps, schema_editor):
    Agendamento = apps.get_model("gestao", "Agendamento")
    concluidos = Agendamento.objects.filter(status="CONCLUIDO").select_related(
        "profissional"
    )
    for agendamento in concluidos.iterator():
        campos_atualizados = []
        if agendamento.iniciado_em is None:
            agendamento.iniciado_em = agendamento.inicio
            campos_atualizados.append("iniciado_em")
        if agendamento.concluido_em is None:
            agendamento.concluido_em = agendamento.atualizado_em or agendamento.fim
            campos_atualizados.append("concluido_em")
        if agendamento.comissao_percentual_aplicada is None:
            agendamento.comissao_percentual_aplicada = (
                agendamento.profissional.comissao_percentual
            )
            campos_atualizados.append("comissao_percentual_aplicada")
        if agendamento.comissao_valor is None and agendamento.preco_cobrado is not None:
            agendamento.comissao_valor = (
                agendamento.preco_cobrado
                * agendamento.comissao_percentual_aplicada
                / Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            campos_atualizados.append("comissao_valor")
        if campos_atualizados:
            agendamento.save(update_fields=campos_atualizados)


class Migration(migrations.Migration):
    dependencies = [
        ("gestao", "0004_agendamento_comissao_percentual_aplicada_and_more"),
    ]

    operations = [
        migrations.RunPython(preencher_historico_financeiro, migrations.RunPython.noop),
    ]
