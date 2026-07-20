from datetime import datetime, time

from django.core.management.base import BaseCommand
from django.utils import timezone

from gestao.models import (
    Agendamento,
    Barbearia,
    Cliente,
    HorarioTrabalho,
    Servico,
    Usuario,
)


class Command(BaseCommand):
    help = "Cria uma barbearia e usuários de demonstração."

    def handle(self, *args, **options):
        barbearia, _ = Barbearia.objects.get_or_create(
            slug="barbearia-demo",
            defaults={
                "nome": "Barbearia Central",
                "telefone": "(32) 99999-0000",
                "email": "contato@barbeariacentral.com.br",
            },
        )

        gestor, criado = Usuario.objects.get_or_create(
            username="gestor",
            defaults={
                "first_name": "Pedro",
                "barbearia": barbearia,
                "papel": Usuario.Papel.PROPRIETARIO,
                "is_staff": True,
            },
        )
        if criado:
            gestor.set_password("Barbearia123!")
            gestor.save()

        barbeiro, criado = Usuario.objects.get_or_create(
            username="barbeiro",
            defaults={
                "first_name": "João",
                "barbearia": barbearia,
                "papel": Usuario.Papel.BARBEIRO,
                "comissao_percentual": 40,
            },
        )
        if criado:
            barbeiro.set_password("Barbearia123!")
            barbeiro.save()

        cliente, _ = Cliente.objects.get_or_create(
            barbearia=barbearia,
            telefone="32988880000",
            defaults={"nome": "Carlos Silva"},
        )
        servico_corte, _ = Servico.objects.get_or_create(
            barbearia=barbearia,
            nome="Corte masculino",
            defaults={"duracao_minutos": 40, "preco": 45},
        )
        servico_barba, _ = Servico.objects.get_or_create(
            barbearia=barbearia,
            nome="Barba",
            defaults={"duracao_minutos": 30, "preco": 35},
        )

        for dia_semana in range(6):
            HorarioTrabalho.objects.get_or_create(
                barbearia=barbearia,
                profissional=barbeiro,
                dia_semana=dia_semana,
                inicio=time(8, 0),
                fim=time(18, 0),
            )

        hoje = timezone.localdate()
        if not Agendamento.objects.filter(
            barbearia=barbearia,
            profissional=barbeiro,
            inicio__date=hoje,
        ).exists():
            Agendamento.objects.create(
                barbearia=barbearia,
                cliente=cliente,
                profissional=barbeiro,
                servico=servico_corte,
                inicio=timezone.make_aware(datetime.combine(hoje, time(9, 0))),
                status=Agendamento.Status.CONCLUIDO,
                forma_pagamento=Agendamento.FormaPagamento.PIX,
            )
            Agendamento.objects.create(
                barbearia=barbearia,
                cliente=cliente,
                profissional=barbeiro,
                servico=servico_barba,
                inicio=timezone.make_aware(datetime.combine(hoje, time(10, 0))),
                status=Agendamento.Status.CONCLUIDO,
                forma_pagamento=Agendamento.FormaPagamento.DINHEIRO,
            )

        self.stdout.write(self.style.SUCCESS("Dados de demonstração criados."))
        self.stdout.write("Gestor: gestor / Barbearia123!")
        self.stdout.write("Barbeiro: barbeiro / Barbearia123!")
        self.stdout.write("Agendamento público: http://127.0.0.1:8000/agendar/barbearia-demo/")
