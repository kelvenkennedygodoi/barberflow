import json
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from .models import Agendamento, NotificacaoWhatsApp, normalizar_telefone


class WhatsAppErro(Exception):
    pass


TIPOS_LEMBRETE = {
    24: NotificacaoWhatsApp.Tipo.LEMBRETE_24H,
    2: NotificacaoWhatsApp.Tipo.LEMBRETE_2H,
}


def normalizar_destinatario(telefone):
    numero = normalizar_telefone(telefone)
    if len(numero) in {10, 11}:
        numero = f"55{numero}"
    if len(numero) < 12 or len(numero) > 15:
        raise WhatsAppErro("O telefone do cliente não possui um formato válido.")
    return numero


def cancelar_notificacoes(agendamento):
    NotificacaoWhatsApp.objects.filter(
        agendamento=agendamento,
        status__in=[
            NotificacaoWhatsApp.Status.PENDENTE,
            NotificacaoWhatsApp.Status.FALHOU,
            NotificacaoWhatsApp.Status.ENVIANDO,
        ],
    ).update(
        status=NotificacaoWhatsApp.Status.CANCELADA,
        atualizada_em=timezone.now(),
    )


def _salvar_notificacao(agendamento, tipo, agendada_para, destinatario):
    notificacao, criada = NotificacaoWhatsApp.objects.get_or_create(
        agendamento=agendamento,
        tipo=tipo,
        defaults={
            "barbearia": agendamento.barbearia,
            "destinatario": destinatario,
            "agendada_para": agendada_para,
        },
    )
    if not criada and notificacao.status != NotificacaoWhatsApp.Status.ENVIADA:
        mudou = (
            notificacao.destinatario != destinatario
            or notificacao.agendada_para != agendada_para
            or notificacao.status == NotificacaoWhatsApp.Status.CANCELADA
        )
        if mudou:
            notificacao.barbearia = agendamento.barbearia
            notificacao.destinatario = destinatario
            notificacao.agendada_para = agendada_para
            notificacao.status = NotificacaoWhatsApp.Status.PENDENTE
            notificacao.tentativas = 0
            notificacao.ultimo_erro = ""
            notificacao.save()
    return notificacao


def sincronizar_notificacoes(agendamento, incluir_confirmacao=False):
    estados_validos = {
        Agendamento.Status.AGENDADO,
        Agendamento.Status.CONFIRMADO,
    }
    if (
        agendamento.status not in estados_validos
        or not agendamento.cliente.aceita_notificacoes_whatsapp
        or not agendamento.cliente.telefone
    ):
        cancelar_notificacoes(agendamento)
        return []

    try:
        destinatario = normalizar_destinatario(agendamento.cliente.telefone)
    except WhatsAppErro:
        cancelar_notificacoes(agendamento)
        return []

    agora = timezone.now()
    notificacoes = []
    if incluir_confirmacao and agendamento.inicio > agora:
        notificacoes.append(
            _salvar_notificacao(
                agendamento,
                NotificacaoWhatsApp.Tipo.CONFIRMACAO,
                agora,
                destinatario,
            )
        )

    NotificacaoWhatsApp.objects.filter(
        agendamento=agendamento,
        tipo=NotificacaoWhatsApp.Tipo.CONFIRMACAO,
        status__in=[
            NotificacaoWhatsApp.Status.PENDENTE,
            NotificacaoWhatsApp.Status.FALHOU,
        ],
    ).update(destinatario=destinatario, atualizada_em=agora)

    horas_ativas = set(settings.WHATSAPP_REMINDER_HOURS)
    for horas, tipo in TIPOS_LEMBRETE.items():
        agendada_para = agendamento.inicio - timedelta(hours=horas)
        if horas in horas_ativas and agendada_para > agora:
            notificacoes.append(
                _salvar_notificacao(
                    agendamento,
                    tipo,
                    agendada_para,
                    destinatario,
                )
            )
        else:
            NotificacaoWhatsApp.objects.filter(
                agendamento=agendamento,
                tipo=tipo,
                status__in=[
                    NotificacaoWhatsApp.Status.PENDENTE,
                    NotificacaoWhatsApp.Status.FALHOU,
                ],
            ).update(
                status=NotificacaoWhatsApp.Status.CANCELADA,
                atualizada_em=agora,
            )
    return notificacoes


def sincronizar_agendamentos_futuros():
    agendamentos = (
        Agendamento.objects.filter(
            inicio__gt=timezone.now(),
            status__in=[
                Agendamento.Status.AGENDADO,
                Agendamento.Status.CONFIRMADO,
            ],
            cliente__aceita_notificacoes_whatsapp=True,
        )
        .select_related("barbearia", "cliente", "profissional", "servico")
        .order_by("inicio")
    )
    for agendamento in agendamentos.iterator():
        sincronizar_notificacoes(agendamento)


def _dados_template(notificacao):
    agendamento = notificacao.agendamento
    inicio = timezone.localtime(agendamento.inicio)
    primeiro_nome = agendamento.cliente.nome.split()[0]
    return [
        primeiro_nome,
        agendamento.barbearia.nome,
        inicio.strftime("%d/%m/%Y"),
        inicio.strftime("%H:%M"),
        agendamento.servico.nome,
        agendamento.profissional.nome_exibicao,
    ]


def _nome_template(notificacao):
    if notificacao.tipo == NotificacaoWhatsApp.Tipo.CONFIRMACAO:
        return settings.WHATSAPP_TEMPLATE_CONFIRMACAO
    return settings.WHATSAPP_TEMPLATE_LEMBRETE


def configuracao_whatsapp_valida():
    if not settings.WHATSAPP_ENABLED:
        return False
    if settings.WHATSAPP_DRY_RUN:
        return True
    return all(
        [
            settings.WHATSAPP_API_VERSION,
            settings.WHATSAPP_PHONE_NUMBER_ID,
            settings.WHATSAPP_ACCESS_TOKEN,
            settings.WHATSAPP_TEMPLATE_CONFIRMACAO,
            settings.WHATSAPP_TEMPLATE_LEMBRETE,
        ]
    )


def enviar_notificacao(notificacao):
    if not configuracao_whatsapp_valida():
        raise WhatsAppErro("A integração do WhatsApp está incompleta ou desativada.")
    if settings.WHATSAPP_DRY_RUN:
        return f"dry-run-{notificacao.pk}"

    nome_template = _nome_template(notificacao)
    if not nome_template:
        raise WhatsAppErro("O modelo de mensagem do WhatsApp não foi configurado.")
    parametros = [
        {"type": "text", "text": str(valor)}
        for valor in _dados_template(notificacao)
    ]
    payload = {
        "messaging_product": "whatsapp",
        "to": notificacao.destinatario,
        "type": "template",
        "template": {
            "name": nome_template,
            "language": {"code": settings.WHATSAPP_LANGUAGE_CODE},
            "components": [{"type": "body", "parameters": parametros}],
        },
    }
    endpoint = (
        f"{settings.WHATSAPP_API_BASE_URL}/{settings.WHATSAPP_API_VERSION}/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    requisicao = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(requisicao, timeout=settings.WHATSAPP_TIMEOUT_SECONDS) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))
    except HTTPError as erro:
        detalhe = erro.read().decode("utf-8", errors="replace")
        raise WhatsAppErro(f"WhatsApp respondeu HTTP {erro.code}: {detalhe[:500]}") from erro
    except (URLError, TimeoutError, json.JSONDecodeError) as erro:
        raise WhatsAppErro(f"Não foi possível comunicar com o WhatsApp: {erro}") from erro

    try:
        return dados["messages"][0]["id"]
    except (KeyError, IndexError, TypeError) as erro:
        raise WhatsAppErro("O WhatsApp não retornou o identificador da mensagem.") from erro
