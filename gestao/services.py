from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from .models import Agendamento, BloqueioAgenda, HorarioTrabalho


def _sobrepoe(inicio, fim, intervalos):
    return any(inicio < intervalo_fim and fim > intervalo_inicio for intervalo_inicio, intervalo_fim in intervalos)


def horarios_disponiveis(barbearia, profissional, servico, data, agendamento_ignorado=None):
    """Retorna datetimes disponíveis para um serviço na agenda do profissional."""
    if (
        not barbearia.ativa
        or profissional.barbearia_id != barbearia.id
        or servico.barbearia_id != barbearia.id
        or not profissional.is_active
        or not servico.ativo
    ):
        return []

    hoje = timezone.localdate()
    limite_dias = barbearia.limite_agendamento_dias
    if data < hoje or data > hoje + timedelta(days=limite_dias):
        return []

    jornadas = HorarioTrabalho.objects.filter(
        barbearia=barbearia,
        profissional=profissional,
        dia_semana=data.weekday(),
        ativo=True,
    )
    if not jornadas.exists():
        return []

    inicio_data = timezone.make_aware(datetime.combine(data, datetime.min.time()))
    fim_data = inicio_data + timedelta(days=1)
    agendamentos = Agendamento.objects.filter(
            barbearia=barbearia,
            profissional=profissional,
            inicio__lt=fim_data,
            fim__gt=inicio_data,
        ).exclude(status=Agendamento.Status.CANCELADO)
    if agendamento_ignorado is not None:
        agendamentos = agendamentos.exclude(pk=agendamento_ignorado.pk)
    ocupados = list(agendamentos.values_list("inicio", "fim"))
    bloqueios = list(
        BloqueioAgenda.objects.filter(
            barbearia=barbearia,
            profissional=profissional,
            inicio__lt=fim_data,
            fim__gt=inicio_data,
        ).values_list("inicio", "fim")
    )

    duracao = timedelta(minutes=servico.duracao_minutos)
    passo = timedelta(minutes=barbearia.intervalo_agendamento_minutos)
    antecedencia = timedelta(minutes=barbearia.antecedencia_agendamento_minutos)
    primeiro_horario_permitido = timezone.now() + antecedencia
    resultado = []

    for jornada in jornadas:
        cursor = timezone.make_aware(datetime.combine(data, jornada.inicio))
        limite = timezone.make_aware(datetime.combine(data, jornada.fim))
        while cursor + duracao <= limite:
            fim = cursor + duracao
            if (
                cursor >= primeiro_horario_permitido
                and not _sobrepoe(cursor, fim, ocupados)
                and not _sobrepoe(cursor, fim, bloqueios)
            ):
                resultado.append(cursor)
            cursor += passo

    return sorted(set(resultado))
