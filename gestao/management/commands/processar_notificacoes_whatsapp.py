from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from gestao.models import Agendamento, NotificacaoWhatsApp
from gestao.whatsapp import (
    WhatsAppErro,
    configuracao_whatsapp_valida,
    enviar_notificacao,
    sincronizar_agendamentos_futuros,
)


class Command(BaseCommand):
    help = "Cria lembretes pendentes e envia a fila do WhatsApp."

    def add_arguments(self, parser):
        parser.add_argument("--limite", type=int, default=100)

    def handle(self, *args, **options):
        if not configuracao_whatsapp_valida():
            self.stdout.write(
                self.style.WARNING(
                    "WhatsApp desativado ou incompleto. Nenhuma mensagem foi enviada."
                )
            )
            return

        sincronizar_agendamentos_futuros()
        agora = timezone.now()
        estados_fila = [
            NotificacaoWhatsApp.Status.PENDENTE,
            NotificacaoWhatsApp.Status.FALHOU,
            NotificacaoWhatsApp.Status.ENVIANDO,
        ]
        NotificacaoWhatsApp.objects.filter(status__in=estados_fila).exclude(
            agendamento__status__in=[
                Agendamento.Status.AGENDADO,
                Agendamento.Status.CONFIRMADO,
            ]
        ).update(
            status=NotificacaoWhatsApp.Status.CANCELADA,
            atualizada_em=agora,
        )
        NotificacaoWhatsApp.objects.filter(
            status__in=estados_fila,
            agendamento__cliente__aceita_notificacoes_whatsapp=False,
        ).update(
            status=NotificacaoWhatsApp.Status.CANCELADA,
            atualizada_em=agora,
        )
        NotificacaoWhatsApp.objects.filter(
            status=NotificacaoWhatsApp.Status.ENVIANDO,
            atualizada_em__lt=agora - timedelta(minutes=20),
        ).update(
            status=NotificacaoWhatsApp.Status.FALHOU,
            ultimo_erro="Envio interrompido antes da conclusão.",
            atualizada_em=agora,
        )
        ids = list(
            NotificacaoWhatsApp.objects.filter(
                status__in=[
                    NotificacaoWhatsApp.Status.PENDENTE,
                    NotificacaoWhatsApp.Status.FALHOU,
                ],
                agendada_para__lte=agora,
                tentativas__lt=settings.WHATSAPP_MAX_RETRIES,
                agendamento__status__in=[
                    Agendamento.Status.AGENDADO,
                    Agendamento.Status.CONFIRMADO,
                ],
                agendamento__cliente__aceita_notificacoes_whatsapp=True,
            )
            .order_by("agendada_para")
            .values_list("pk", flat=True)[: max(1, options["limite"])]
        )

        enviadas = 0
        falhas = 0
        for notificacao_id in ids:
            with transaction.atomic():
                notificacao = (
                    NotificacaoWhatsApp.objects.select_for_update()
                    .select_related(
                        "agendamento__barbearia",
                        "agendamento__cliente",
                        "agendamento__profissional",
                        "agendamento__servico",
                    )
                    .get(pk=notificacao_id)
                )
                if notificacao.status not in {
                    NotificacaoWhatsApp.Status.PENDENTE,
                    NotificacaoWhatsApp.Status.FALHOU,
                }:
                    continue
                notificacao.status = NotificacaoWhatsApp.Status.ENVIANDO
                notificacao.tentativas = F("tentativas") + 1
                notificacao.save(
                    update_fields=["status", "tentativas", "atualizada_em"]
                )
            notificacao.refresh_from_db()

            try:
                mensagem_id = enviar_notificacao(notificacao)
            except WhatsAppErro as erro:
                falhas += 1
                notificacao.status = NotificacaoWhatsApp.Status.FALHOU
                notificacao.ultimo_erro = str(erro)[:2000]
                notificacao.save(
                    update_fields=[
                        "status",
                        "ultimo_erro",
                        "atualizada_em",
                    ]
                )
            else:
                enviadas += 1
                notificacao.status = NotificacaoWhatsApp.Status.ENVIADA
                notificacao.enviada_em = timezone.now()
                notificacao.mensagem_id = mensagem_id
                notificacao.ultimo_erro = ""
                notificacao.save(
                    update_fields=[
                        "status",
                        "enviada_em",
                        "mensagem_id",
                        "ultimo_erro",
                        "atualizada_em",
                    ]
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Fila processada: {enviadas} enviada(s), {falhas} falha(s)."
            )
        )
