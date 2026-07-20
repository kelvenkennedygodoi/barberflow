from datetime import datetime, time, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    Agendamento,
    Barbearia,
    BloqueioAgenda,
    Cliente,
    HorarioTrabalho,
    NotificacaoWhatsApp,
    Servico,
    Usuario,
)
from .whatsapp import WhatsAppErro, cancelar_notificacoes, sincronizar_notificacoes


class BaseTestCase(TestCase):
    def setUp(self):
        self.barbearia_a = Barbearia.objects.create(nome="Barbearia A", slug="a")
        self.barbearia_b = Barbearia.objects.create(nome="Barbearia B", slug="b")
        self.gestor_a = Usuario.objects.create_user(
            username="gestor_a",
            password="senha-forte-123",
            barbearia=self.barbearia_a,
            papel=Usuario.Papel.PROPRIETARIO,
        )
        self.barbeiro_a = Usuario.objects.create_user(
            username="barbeiro_a",
            password="senha-forte-123",
            barbearia=self.barbearia_a,
            papel=Usuario.Papel.BARBEIRO,
        )
        self.cliente_a = Cliente.objects.create(
            barbearia=self.barbearia_a,
            nome="Cliente da A",
        )
        self.cliente_b = Cliente.objects.create(
            barbearia=self.barbearia_b,
            nome="Cliente secreto da B",
        )
        self.servico_a = Servico.objects.create(
            barbearia=self.barbearia_a,
            nome="Corte",
            duracao_minutos=40,
            preco=45,
        )


class IsolamentoPorBarbeariaTests(BaseTestCase):
    def test_lista_exibe_apenas_clientes_da_barbearia_do_usuario(self):
        self.client.force_login(self.gestor_a)

        response = self.client.get(reverse("cliente_lista"))

        self.assertContains(response, "Cliente da A")
        self.assertNotContains(response, "Cliente secreto da B")

    def test_usuario_nao_edita_cliente_de_outra_barbearia(self):
        self.client.force_login(self.gestor_a)

        response = self.client.get(reverse("cliente_editar", args=[self.cliente_b.pk]))

        self.assertEqual(response.status_code, 404)

    def test_novo_cliente_recebe_barbearia_do_usuario(self):
        self.client.force_login(self.gestor_a)

        response = self.client.post(
            reverse("cliente_criar"),
            {"nome": "Novo cliente", "telefone": "31999990000", "ativo": True},
        )

        self.assertRedirects(response, reverse("cliente_lista"))
        self.assertTrue(
            Cliente.objects.filter(
                nome="Novo cliente",
                barbearia=self.barbearia_a,
            ).exists()
        )


class AgendamentoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.inicio = timezone.now().replace(second=0, microsecond=0) + timedelta(days=1)

    def criar_agendamento(self, **overrides):
        dados = {
            "barbearia": self.barbearia_a,
            "cliente": self.cliente_a,
            "profissional": self.barbeiro_a,
            "servico": self.servico_a,
            "inicio": self.inicio,
        }
        dados.update(overrides)
        return Agendamento.objects.create(**dados)

    def test_calcula_fim_e_copia_preco_do_servico(self):
        agendamento = self.criar_agendamento()

        self.assertEqual(agendamento.fim, self.inicio + timedelta(minutes=40))
        self.assertEqual(agendamento.preco_cobrado, self.servico_a.preco)

    def test_impede_horarios_sobrepostos_para_mesmo_profissional(self):
        self.criar_agendamento()

        with self.assertRaises(ValidationError):
            self.criar_agendamento(inicio=self.inicio + timedelta(minutes=20))

    def test_agendamento_cancelado_nao_bloqueia_horario(self):
        self.criar_agendamento(status=Agendamento.Status.CANCELADO)

        segundo = self.criar_agendamento()

        self.assertIsNotNone(segundo.pk)

    def test_rejeita_cliente_de_outra_barbearia(self):
        with self.assertRaises(ValidationError):
            self.criar_agendamento(cliente=self.cliente_b)


class AutenticacaoTests(BaseTestCase):
    def test_dashboard_exige_login(self):
        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

    def test_usuario_autenticado_visualiza_dashboard_e_formulario_da_agenda(self):
        self.client.force_login(self.gestor_a)

        dashboard = self.client.get(reverse("dashboard"))
        formulario = self.client.get(reverse("agendamento_criar"))

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(formulario.status_code, 200)
        self.assertContains(formulario, self.cliente_a.nome)
        self.assertContains(formulario, self.barbeiro_a.username)


class AutoAgendamentoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.data = timezone.localdate() + timedelta(days=1)
        HorarioTrabalho.objects.create(
            barbearia=self.barbearia_a,
            profissional=self.barbeiro_a,
            dia_semana=self.data.weekday(),
            inicio=time(9, 0),
            fim=time(12, 0),
        )

    def parametros_horarios(self):
        return {
            "profissional": self.barbeiro_a.pk,
            "servico": self.servico_a.pk,
            "data": self.data.isoformat(),
        }

    def dados_formulario(self, **overrides):
        dados = {
            "nome": "Cliente Online",
            "telefone": "(32) 99999-1234",
            "email": "cliente@example.com",
            "servico": self.servico_a.pk,
            "profissional": self.barbeiro_a.pk,
            "data": self.data.isoformat(),
            "horario": "09:00",
            "confirmacao_dados": "on",
            "website": "",
        }
        dados.update(overrides)
        return dados

    def test_pagina_publica_nao_exige_login(self):
        response = self.client.get(
            reverse("agendamento_publico", args=[self.barbearia_a.slug])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.barbearia_a.nome)
        self.assertContains(response, "Confirmar agendamento")

    def test_endpoint_retorna_apenas_horarios_disponiveis(self):
        response = self.client.get(
            reverse("horarios_disponiveis_publico", args=[self.barbearia_a.slug]),
            self.parametros_horarios(),
        )

        self.assertEqual(response.status_code, 200)
        valores = [item["valor"] for item in response.json()["horarios"]]
        self.assertIn("09:00", valores)
        self.assertIn("11:15", valores)
        self.assertNotIn("11:30", valores)

    def test_horario_ocupado_e_bloqueado_nao_e_oferecido(self):
        inicio_ocupado = timezone.make_aware(datetime.combine(self.data, time(9, 0)))
        Agendamento.objects.create(
            barbearia=self.barbearia_a,
            cliente=self.cliente_a,
            profissional=self.barbeiro_a,
            servico=self.servico_a,
            inicio=inicio_ocupado,
        )
        BloqueioAgenda.objects.create(
            barbearia=self.barbearia_a,
            profissional=self.barbeiro_a,
            inicio=timezone.make_aware(datetime.combine(self.data, time(10, 0))),
            fim=timezone.make_aware(datetime.combine(self.data, time(11, 0))),
            motivo="Almoço",
        )

        response = self.client.get(
            reverse("horarios_disponiveis_publico", args=[self.barbearia_a.slug]),
            self.parametros_horarios(),
        )

        valores = [item["valor"] for item in response.json()["horarios"]]
        self.assertNotIn("09:00", valores)
        self.assertNotIn("09:30", valores)
        self.assertNotIn("10:00", valores)
        self.assertIn("11:00", valores)

    def test_cliente_consegue_criar_agendamento(self):
        response = self.client.post(
            reverse("agendamento_publico", args=[self.barbearia_a.slug]),
            self.dados_formulario(),
        )

        agendamento = Agendamento.objects.get(origem=Agendamento.Origem.ONLINE)
        self.assertRedirects(
            response,
            reverse("agendamento_publico_confirmacao", args=[self.barbearia_a.slug]),
        )
        self.assertEqual(agendamento.profissional, self.barbeiro_a)
        self.assertEqual(agendamento.servico, self.servico_a)
        self.assertEqual(agendamento.cliente.telefone, "32999991234")
        self.assertEqual(agendamento.status, Agendamento.Status.AGENDADO)

    def test_nao_aceita_horario_que_foi_ocupado(self):
        inicio = timezone.make_aware(datetime.combine(self.data, time(9, 0)))
        Agendamento.objects.create(
            barbearia=self.barbearia_a,
            cliente=self.cliente_a,
            profissional=self.barbeiro_a,
            servico=self.servico_a,
            inicio=inicio,
        )

        response = self.client.post(
            reverse("agendamento_publico", args=[self.barbearia_a.slug]),
            self.dados_formulario(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "não está mais disponível")
        self.assertEqual(Agendamento.objects.count(), 1)

    def test_nao_consulta_profissional_de_outra_barbearia(self):
        barbeiro_b = Usuario.objects.create_user(
            username="barbeiro_b",
            password="senha-forte-123",
            barbearia=self.barbearia_b,
            papel=Usuario.Papel.BARBEIRO,
        )
        parametros = self.parametros_horarios()
        parametros["profissional"] = barbeiro_b.pk

        response = self.client.get(
            reverse("horarios_disponiveis_publico", args=[self.barbearia_a.slug]),
            parametros,
        )

        self.assertEqual(response.status_code, 404)

    def test_consentimento_whatsapp_nao_vem_marcado(self):
        response = self.client.get(reverse("agendamento_publico", args=[self.barbearia_a.slug]))

        self.assertNotContains(response, 'name="aceita_notificacoes_whatsapp" checked')

    def test_cliente_existente_tem_nome_e_email_atualizados(self):
        Cliente.objects.create(
            barbearia=self.barbearia_a,
            nome="Nome antigo",
            telefone="32999991234",
            email="antigo@example.com",
        )

        self.client.post(
            reverse("agendamento_publico", args=[self.barbearia_a.slug]),
            self.dados_formulario(nome="Nome atualizado", email="novo@example.com"),
        )

        cliente = Cliente.objects.get(barbearia=self.barbearia_a, telefone="32999991234")
        self.assertEqual(cliente.nome, "Nome atualizado")
        self.assertEqual(cliente.email, "novo@example.com")

    def test_cliente_pode_consultar_e_cancelar_por_token(self):
        self.client.post(
            reverse("agendamento_publico", args=[self.barbearia_a.slug]),
            self.dados_formulario(),
        )
        agendamento = Agendamento.objects.get(origem=Agendamento.Origem.ONLINE)

        consulta = self.client.get(
            reverse("agendamento_publico_gerenciar", args=[self.barbearia_a.slug, agendamento.token_publico])
        )
        cancelamento = self.client.post(
            reverse("agendamento_publico_cancelar", args=[self.barbearia_a.slug, agendamento.token_publico])
        )

        agendamento.refresh_from_db()
        self.assertEqual(consulta.status_code, 200)
        self.assertEqual(cancelamento.status_code, 302)
        self.assertEqual(agendamento.status, Agendamento.Status.CANCELADO)

    def test_cliente_pode_reagendar_por_token(self):
        self.client.post(
            reverse("agendamento_publico", args=[self.barbearia_a.slug]),
            self.dados_formulario(),
        )
        agendamento = Agendamento.objects.get(origem=Agendamento.Origem.ONLINE)

        response = self.client.post(
            reverse("agendamento_publico_reagendar", args=[self.barbearia_a.slug, agendamento.token_publico]),
            {
                "servico": self.servico_a.pk,
                "profissional": self.barbeiro_a.pk,
                "data": self.data.isoformat(),
                "horario": "10:00",
            },
        )

        agendamento.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(timezone.localtime(agendamento.inicio).strftime("%H:%M"), "10:00")


class AgendaVisualTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.data = timezone.localdate() + timedelta(days=2)
        self.inicio = timezone.make_aware(datetime.combine(self.data, time(9, 0)))
        self.agendamento = Agendamento.objects.create(
            barbearia=self.barbearia_a,
            cliente=self.cliente_a,
            profissional=self.barbeiro_a,
            servico=self.servico_a,
            inicio=self.inicio,
            status=Agendamento.Status.CONFIRMADO,
        )

    def test_exibe_agenda_diaria_com_coluna_do_barbeiro(self):
        self.client.force_login(self.gestor_a)

        response = self.client.get(
            reverse("agenda_visual"),
            {"modo": "dia", "data": self.data.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "agenda-day-canvas")
        self.assertContains(response, self.cliente_a.nome)
        self.assertContains(response, self.barbeiro_a.nome_exibicao)

    def test_exibe_sete_dias_na_visualizacao_semanal(self):
        self.client.force_login(self.gestor_a)

        response = self.client.get(
            reverse("agenda_visual"),
            {"modo": "semana", "data": self.data.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["dias_semana"]), 7)
        self.assertContains(response, "agenda-week-grid")
        self.assertContains(response, self.cliente_a.nome)

    def test_filtro_de_status_remove_outros_atendimentos(self):
        outro_cliente = Cliente.objects.create(
            barbearia=self.barbearia_a,
            nome="Cliente cancelado",
        )
        Agendamento.objects.create(
            barbearia=self.barbearia_a,
            cliente=outro_cliente,
            profissional=self.barbeiro_a,
            servico=self.servico_a,
            inicio=self.inicio + timedelta(hours=2),
            status=Agendamento.Status.CANCELADO,
        )
        self.client.force_login(self.gestor_a)

        response = self.client.get(
            reverse("agenda_visual"),
            {
                "modo": "dia",
                "data": self.data.isoformat(),
                "status": Agendamento.Status.CONFIRMADO,
            },
        )

        self.assertContains(response, self.cliente_a.nome)
        self.assertNotContains(response, outro_cliente.nome)

    def test_barbeiro_visualiza_somente_a_propria_agenda(self):
        colega = Usuario.objects.create_user(
            username="colega",
            password="senha-forte-123",
            first_name="Barbeiro Colega",
            barbearia=self.barbearia_a,
            papel=Usuario.Papel.BARBEIRO,
        )
        cliente_colega = Cliente.objects.create(
            barbearia=self.barbearia_a,
            nome="Cliente do colega",
        )
        Agendamento.objects.create(
            barbearia=self.barbearia_a,
            cliente=cliente_colega,
            profissional=colega,
            servico=self.servico_a,
            inicio=self.inicio,
        )
        self.client.force_login(self.barbeiro_a)

        response = self.client.get(
            reverse("agenda_visual"),
            {"modo": "dia", "data": self.data.isoformat()},
        )

        self.assertContains(response, self.cliente_a.nome)
        self.assertNotContains(response, cliente_colega.nome)
        self.assertNotContains(response, colega.nome_exibicao)


class DisponibilidadeEquipeTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.recepcionista = Usuario.objects.create_user(
            username="recepcao",
            password="senha-forte-123",
            barbearia=self.barbearia_a,
            papel=Usuario.Papel.RECEPCIONISTA,
        )

    def test_proprietario_visualiza_equipe_e_disponibilidade(self):
        self.client.force_login(self.gestor_a)

        equipe = self.client.get(reverse("equipe_lista"))
        disponibilidade = self.client.get(
            reverse("disponibilidade_profissional", args=[self.barbeiro_a.pk])
        )

        self.assertEqual(equipe.status_code, 200)
        self.assertEqual(disponibilidade.status_code, 200)
        self.assertContains(equipe, self.barbeiro_a.nome_exibicao)
        self.assertContains(disponibilidade, "Jornada semanal")

    def test_recepcionista_nao_altera_disponibilidade(self):
        self.client.force_login(self.recepcionista)

        response = self.client.get(reverse("equipe_lista"))

        self.assertEqual(response.status_code, 403)

    def test_cria_periodo_de_trabalho_pela_interface(self):
        self.client.force_login(self.gestor_a)

        response = self.client.post(
            reverse("horario_trabalho_criar", args=[self.barbeiro_a.pk]),
            {
                "dia_semana": HorarioTrabalho.DiaSemana.SEGUNDA,
                "inicio": "08:00",
                "fim": "12:00",
                "ativo": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse("disponibilidade_profissional", args=[self.barbeiro_a.pk]),
        )
        self.assertTrue(
            HorarioTrabalho.objects.filter(
                profissional=self.barbeiro_a,
                inicio=time(8, 0),
                fim=time(12, 0),
            ).exists()
        )

    def test_rejeita_periodos_de_trabalho_sobrepostos(self):
        HorarioTrabalho.objects.create(
            barbearia=self.barbearia_a,
            profissional=self.barbeiro_a,
            dia_semana=HorarioTrabalho.DiaSemana.SEGUNDA,
            inicio=time(8, 0),
            fim=time(12, 0),
        )
        self.client.force_login(self.gestor_a)

        response = self.client.post(
            reverse("horario_trabalho_criar", args=[self.barbeiro_a.pk]),
            {
                "dia_semana": HorarioTrabalho.DiaSemana.SEGUNDA,
                "inicio": "11:00",
                "fim": "15:00",
                "ativo": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "se sobrepõe")
        self.assertEqual(HorarioTrabalho.objects.count(), 1)

    def test_cria_e_remove_indisponibilidade(self):
        inicio = timezone.localtime(timezone.now() + timedelta(days=3)).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        fim = inicio + timedelta(hours=2)
        self.client.force_login(self.gestor_a)

        criacao = self.client.post(
            reverse("bloqueio_agenda_criar", args=[self.barbeiro_a.pk]),
            {
                "inicio": inicio.strftime("%Y-%m-%dT%H:%M"),
                "fim": fim.strftime("%Y-%m-%dT%H:%M"),
                "motivo": "Consulta",
            },
        )

        bloqueio = BloqueioAgenda.objects.get(profissional=self.barbeiro_a)
        self.assertRedirects(
            criacao,
            reverse("disponibilidade_profissional", args=[self.barbeiro_a.pk]),
        )

        exclusao = self.client.post(
            reverse(
                "bloqueio_agenda_excluir",
                args=[self.barbeiro_a.pk, bloqueio.pk],
            )
        )

        self.assertRedirects(
            exclusao,
            reverse("disponibilidade_profissional", args=[self.barbeiro_a.pk]),
        )
        self.assertFalse(BloqueioAgenda.objects.filter(pk=bloqueio.pk).exists())

    def test_nao_configura_barbeiro_de_outra_barbearia(self):
        barbeiro_b = Usuario.objects.create_user(
            username="barbeiro_externo",
            password="senha-forte-123",
            barbearia=self.barbearia_b,
            papel=Usuario.Papel.BARBEIRO,
        )
        self.client.force_login(self.gestor_a)

        response = self.client.get(
            reverse("disponibilidade_profissional", args=[barbeiro_b.pk])
        )

        self.assertEqual(response.status_code, 404)


class GerenciamentoFuncionariosTests(BaseTestCase):
    def dados_funcionario(self, **overrides):
        dados = {
            "first_name": "Lucas",
            "last_name": "Barbosa",
            "username": "lucas.barbosa",
            "email": "lucas@example.com",
            "telefone": "32999990001",
            "papel": Usuario.Papel.BARBEIRO,
            "comissao_percentual": "40.00",
            "password1": "SenhaMuitoForte2026!",
            "password2": "SenhaMuitoForte2026!",
        }
        dados.update(overrides)
        return dados

    def test_proprietario_cadastra_barbeiro_com_acesso(self):
        self.client.force_login(self.gestor_a)

        response = self.client.post(
            reverse("funcionario_criar"),
            self.dados_funcionario(),
        )

        self.assertRedirects(response, reverse("equipe_lista"))
        funcionario = Usuario.objects.get(username="lucas.barbosa")
        self.assertEqual(funcionario.barbearia, self.barbearia_a)
        self.assertEqual(funcionario.papel, Usuario.Papel.BARBEIRO)
        self.assertTrue(funcionario.check_password("SenhaMuitoForte2026!"))

    def test_comissao_da_recepcionista_e_zerada(self):
        self.client.force_login(self.gestor_a)

        response = self.client.post(
            reverse("funcionario_criar"),
            self.dados_funcionario(
                username="recepcionista.nova",
                email="recepcao.nova@example.com",
                papel=Usuario.Papel.RECEPCIONISTA,
                comissao_percentual="75.00",
            ),
        )

        self.assertRedirects(response, reverse("equipe_lista"))
        funcionario = Usuario.objects.get(username="recepcionista.nova")
        self.assertEqual(funcionario.comissao_percentual, 0)

    def test_edita_dados_comissao_e_redefine_senha(self):
        self.client.force_login(self.gestor_a)

        response = self.client.post(
            reverse("funcionario_editar", args=[self.barbeiro_a.pk]),
            {
                "first_name": "João",
                "last_name": "Silva",
                "username": self.barbeiro_a.username,
                "email": "joao@example.com",
                "telefone": "32988887777",
                "papel": Usuario.Papel.BARBEIRO,
                "comissao_percentual": "45.00",
                "nova_senha1": "NovaSenhaMuitoForte2026!",
                "nova_senha2": "NovaSenhaMuitoForte2026!",
            },
        )

        self.assertRedirects(response, reverse("equipe_lista"))
        self.barbeiro_a.refresh_from_db()
        self.assertEqual(self.barbeiro_a.first_name, "João")
        self.assertEqual(self.barbeiro_a.comissao_percentual, 45)
        self.assertTrue(self.barbeiro_a.check_password("NovaSenhaMuitoForte2026!"))

    def test_nao_muda_funcao_de_barbeiro_com_historico(self):
        HorarioTrabalho.objects.create(
            barbearia=self.barbearia_a,
            profissional=self.barbeiro_a,
            dia_semana=HorarioTrabalho.DiaSemana.SEGUNDA,
            inicio=time(8, 0),
            fim=time(12, 0),
        )
        self.client.force_login(self.gestor_a)

        response = self.client.post(
            reverse("funcionario_editar", args=[self.barbeiro_a.pk]),
            {
                "first_name": "Barbeiro",
                "last_name": "Teste",
                "username": self.barbeiro_a.username,
                "email": "",
                "telefone": "",
                "papel": Usuario.Papel.RECEPCIONISTA,
                "comissao_percentual": "0.00",
                "nova_senha1": "",
                "nova_senha2": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "possui agenda ou histórico")
        self.barbeiro_a.refresh_from_db()
        self.assertEqual(self.barbeiro_a.papel, Usuario.Papel.BARBEIRO)

    def test_nao_desativa_barbeiro_com_atendimento_futuro(self):
        inicio = timezone.now() + timedelta(days=3)
        Agendamento.objects.create(
            barbearia=self.barbearia_a,
            cliente=self.cliente_a,
            profissional=self.barbeiro_a,
            servico=self.servico_a,
            inicio=inicio,
        )
        self.client.force_login(self.gestor_a)

        response = self.client.post(
            reverse("funcionario_alterar_status", args=[self.barbeiro_a.pk])
        )

        self.assertRedirects(response, reverse("equipe_lista"))
        self.barbeiro_a.refresh_from_db()
        self.assertTrue(self.barbeiro_a.is_active)

    def test_desativa_e_reativa_recepcionista(self):
        recepcionista = Usuario.objects.create_user(
            username="recepcionista_status",
            password="senha-forte-123",
            barbearia=self.barbearia_a,
            papel=Usuario.Papel.RECEPCIONISTA,
        )
        self.client.force_login(self.gestor_a)
        url = reverse("funcionario_alterar_status", args=[recepcionista.pk])

        self.client.post(url)
        recepcionista.refresh_from_db()
        self.assertFalse(recepcionista.is_active)

        self.client.post(url)
        recepcionista.refresh_from_db()
        self.assertTrue(recepcionista.is_active)

    def test_nao_edita_funcionario_de_outra_barbearia(self):
        externo = Usuario.objects.create_user(
            username="funcionario_externo",
            password="senha-forte-123",
            barbearia=self.barbearia_b,
            papel=Usuario.Papel.RECEPCIONISTA,
        )
        self.client.force_login(self.gestor_a)

        response = self.client.get(reverse("funcionario_editar", args=[externo.pk]))

        self.assertEqual(response.status_code, 404)

    def test_recepcionista_nao_cadastra_funcionario(self):
        recepcionista = Usuario.objects.create_user(
            username="recepcionista_sem_permissao",
            password="senha-forte-123",
            barbearia=self.barbearia_a,
            papel=Usuario.Papel.RECEPCIONISTA,
        )
        self.client.force_login(recepcionista)

        response = self.client.get(reverse("funcionario_criar"))

        self.assertEqual(response.status_code, 403)


class TelaOperacionalBarbeiroTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.barbeiro_a.comissao_percentual = Decimal("40.00")
        self.barbeiro_a.save(update_fields=["comissao_percentual"])
        hoje = timezone.localdate()
        self.inicio = timezone.make_aware(datetime.combine(hoje, time(9, 0)))
        self.agendamento = Agendamento.objects.create(
            barbearia=self.barbearia_a,
            cliente=self.cliente_a,
            profissional=self.barbeiro_a,
            servico=self.servico_a,
            inicio=self.inicio,
        )

    def test_dashboard_do_barbeiro_abre_meu_dia(self):
        self.client.force_login(self.barbeiro_a)

        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(response, reverse("meu_dia"))

    def test_meu_dia_exibe_somente_atendimentos_do_barbeiro_logado(self):
        colega = Usuario.objects.create_user(
            username="barbeiro_colega_operacao",
            password="senha-forte-123",
            barbearia=self.barbearia_a,
            papel=Usuario.Papel.BARBEIRO,
        )
        cliente_colega = Cliente.objects.create(
            barbearia=self.barbearia_a,
            nome="Cliente reservado do colega",
        )
        Agendamento.objects.create(
            barbearia=self.barbearia_a,
            cliente=cliente_colega,
            profissional=colega,
            servico=self.servico_a,
            inicio=self.inicio,
        )
        self.client.force_login(self.barbeiro_a)

        response = self.client.get(reverse("meu_dia"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.cliente_a.nome)
        self.assertNotContains(response, cliente_colega.nome)

    def test_area_operacional_e_exclusiva_do_barbeiro(self):
        self.client.force_login(self.gestor_a)

        response = self.client.get(reverse("meu_dia"))

        self.assertEqual(response.status_code, 403)

    def test_barbeiro_confirma_chegada_e_inicia_atendimento(self):
        self.client.force_login(self.barbeiro_a)

        confirmacao = self.client.post(
            reverse("atendimento_confirmar_chegada", args=[self.agendamento.pk])
        )
        self.assertRedirects(confirmacao, reverse("meu_dia"))
        self.agendamento.refresh_from_db()
        self.assertEqual(self.agendamento.status, Agendamento.Status.CONFIRMADO)

        inicio = self.client.post(
            reverse("atendimento_iniciar", args=[self.agendamento.pk])
        )
        self.assertRedirects(inicio, reverse("meu_dia"))
        self.agendamento.refresh_from_db()
        self.assertEqual(self.agendamento.status, Agendamento.Status.EM_ATENDIMENTO)
        self.assertIsNotNone(self.agendamento.iniciado_em)

    def test_nao_inicia_sem_confirmar_chegada(self):
        self.client.force_login(self.barbeiro_a)

        response = self.client.post(
            reverse("atendimento_iniciar", args=[self.agendamento.pk])
        )

        self.assertRedirects(response, reverse("meu_dia"))
        self.agendamento.refresh_from_db()
        self.assertEqual(self.agendamento.status, Agendamento.Status.AGENDADO)

    def test_registra_falta_do_cliente(self):
        self.client.force_login(self.barbeiro_a)

        response = self.client.post(
            reverse("atendimento_registrar_falta", args=[self.agendamento.pk])
        )

        self.assertRedirects(response, reverse("meu_dia"))
        self.agendamento.refresh_from_db()
        self.assertEqual(self.agendamento.status, Agendamento.Status.FALTOU)

    def test_conclusao_registra_pagamento_valor_e_comissao(self):
        self.agendamento.status = Agendamento.Status.EM_ATENDIMENTO
        self.agendamento.save()
        self.client.force_login(self.barbeiro_a)

        response = self.client.post(
            reverse("atendimento_concluir", args=[self.agendamento.pk]),
            {
                "preco_cobrado": "50.00",
                "forma_pagamento": Agendamento.FormaPagamento.PIX,
            },
        )

        self.assertRedirects(response, reverse("meu_dia"))
        self.agendamento.refresh_from_db()
        self.assertEqual(self.agendamento.status, Agendamento.Status.CONCLUIDO)
        self.assertEqual(self.agendamento.preco_cobrado, Decimal("50.00"))
        self.assertEqual(
            self.agendamento.forma_pagamento,
            Agendamento.FormaPagamento.PIX,
        )
        self.assertEqual(
            self.agendamento.comissao_percentual_aplicada,
            Decimal("40.00"),
        )
        self.assertEqual(self.agendamento.comissao_valor, Decimal("20.00"))
        self.assertIsNotNone(self.agendamento.concluido_em)

    def test_comissao_concluida_nao_muda_com_novo_percentual(self):
        self.agendamento.status = Agendamento.Status.CONCLUIDO
        self.agendamento.preco_cobrado = Decimal("50.00")
        self.agendamento.save()
        self.barbeiro_a.comissao_percentual = Decimal("60.00")
        self.barbeiro_a.save(update_fields=["comissao_percentual"])

        self.agendamento.refresh_from_db()

        self.assertEqual(self.agendamento.comissao_valor, Decimal("20.00"))
        self.assertEqual(
            self.agendamento.comissao_percentual_aplicada,
            Decimal("40.00"),
        )

    def test_barbeiro_nao_atualiza_atendimento_de_colega(self):
        colega = Usuario.objects.create_user(
            username="colega_protegido",
            password="senha-forte-123",
            barbearia=self.barbearia_a,
            papel=Usuario.Papel.BARBEIRO,
        )
        atendimento_colega = Agendamento.objects.create(
            barbearia=self.barbearia_a,
            cliente=self.cliente_a,
            profissional=colega,
            servico=self.servico_a,
            inicio=self.inicio + timedelta(hours=2),
        )
        self.client.force_login(self.barbeiro_a)

        response = self.client.post(
            reverse(
                "atendimento_confirmar_chegada",
                args=[atendimento_colega.pk],
            )
        )

        self.assertEqual(response.status_code, 404)
        atendimento_colega.refresh_from_db()
        self.assertEqual(atendimento_colega.status, Agendamento.Status.AGENDADO)


class RelatoriosFinanceirosTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.barbeiro_a.comissao_percentual = Decimal("40.00")
        self.barbeiro_a.save(update_fields=["comissao_percentual"])
        self.colega = Usuario.objects.create_user(
            username="barbeiro_financeiro",
            password="senha-forte-123",
            first_name="Marcos",
            barbearia=self.barbearia_a,
            papel=Usuario.Papel.BARBEIRO,
            comissao_percentual=Decimal("30.00"),
        )
        hoje = timezone.localdate()
        self.data_inicio = hoje - timedelta(days=2)
        self.data_fim = hoje + timedelta(days=1)
        self.parametros = {
            "data_inicio": self.data_inicio.isoformat(),
            "data_fim": self.data_fim.isoformat(),
        }
        self.atendimento_pix = self.criar_atendimento(
            profissional=self.barbeiro_a,
            hora=time(9, 0),
            preco=Decimal("50.00"),
            pagamento=Agendamento.FormaPagamento.PIX,
        )
        self.atendimento_cartao = self.criar_atendimento(
            profissional=self.colega,
            hora=time(11, 0),
            preco=Decimal("100.00"),
            pagamento=Agendamento.FormaPagamento.CARTAO_CREDITO,
        )

        self.criar_atendimento(
            profissional=self.barbeiro_a,
            hora=time(13, 0),
            preco=Decimal("500.00"),
            pagamento=Agendamento.FormaPagamento.DINHEIRO,
            status=Agendamento.Status.CANCELADO,
        )
        barbearia_externa = self.barbearia_b
        barbeiro_externo = Usuario.objects.create_user(
            username="barbeiro_financeiro_externo",
            password="senha-forte-123",
            barbearia=barbearia_externa,
            papel=Usuario.Papel.BARBEIRO,
            comissao_percentual=Decimal("50.00"),
        )
        servico_externo = Servico.objects.create(
            barbearia=barbearia_externa,
            nome="Serviço externo",
            duracao_minutos=30,
            preco=Decimal("999.00"),
        )
        Agendamento.objects.create(
            barbearia=barbearia_externa,
            cliente=self.cliente_b,
            profissional=barbeiro_externo,
            servico=servico_externo,
            inicio=timezone.make_aware(datetime.combine(hoje, time(10, 0))),
            status=Agendamento.Status.CONCLUIDO,
            forma_pagamento=Agendamento.FormaPagamento.PIX,
        )

    def criar_atendimento(
        self,
        *,
        profissional,
        hora,
        preco,
        pagamento,
        status=Agendamento.Status.CONCLUIDO,
    ):
        return Agendamento.objects.create(
            barbearia=self.barbearia_a,
            cliente=self.cliente_a,
            profissional=profissional,
            servico=self.servico_a,
            inicio=timezone.make_aware(
                datetime.combine(timezone.localdate(), hora)
            ),
            status=status,
            preco_cobrado=preco,
            forma_pagamento=pagamento,
        )

    def test_painel_calcula_faturamento_ticket_comissao_e_liquido(self):
        self.client.force_login(self.gestor_a)

        response = self.client.get(reverse("financeiro"), self.parametros)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["faturamento"], Decimal("150.00"))
        self.assertEqual(response.context["comissoes"], Decimal("50.00"))
        self.assertEqual(response.context["liquido"], Decimal("100.00"))
        self.assertEqual(response.context["ticket_medio"], Decimal("75.00"))
        self.assertEqual(response.context["atendimentos"], 2)

    def test_relatorio_separa_pagamentos_e_comissoes_por_barbeiro(self):
        self.client.force_login(self.gestor_a)

        response = self.client.get(reverse("financeiro"), self.parametros)

        pagamentos = {item["nome"]: item for item in response.context["pagamentos"]}
        self.assertEqual(pagamentos["PIX"]["total"], Decimal("50.00"))
        self.assertEqual(
            pagamentos["Cartão de crédito"]["total"],
            Decimal("100.00"),
        )
        comissoes = {
            item["nome"]: item
            for item in response.context["comissoes_profissionais"]
        }
        self.assertEqual(comissoes[self.barbeiro_a.nome_exibicao]["comissao"], 20)
        self.assertEqual(comissoes[self.colega.nome_exibicao]["comissao"], 30)

    def test_filtro_por_barbeiro_limita_todos_os_indicadores(self):
        self.client.force_login(self.gestor_a)
        parametros = {**self.parametros, "profissional": self.barbeiro_a.pk}

        response = self.client.get(reverse("financeiro"), parametros)

        self.assertEqual(response.context["faturamento"], Decimal("50.00"))
        self.assertEqual(response.context["comissoes"], Decimal("20.00"))
        self.assertEqual(response.context["atendimentos"], 1)
        self.assertEqual(len(response.context["comissoes_profissionais"]), 1)
        self.assertEqual(
            response.context["comissoes_profissionais"][0]["nome"],
            self.barbeiro_a.nome_exibicao,
        )

    def test_filtro_por_forma_de_pagamento(self):
        self.client.force_login(self.gestor_a)
        parametros = {
            **self.parametros,
            "forma_pagamento": Agendamento.FormaPagamento.PIX,
        }

        response = self.client.get(reverse("financeiro"), parametros)

        self.assertEqual(response.context["faturamento"], Decimal("50.00"))
        self.assertEqual(response.context["atendimentos"], 1)

    def test_relatorio_nao_inclui_cancelados_nem_outra_barbearia(self):
        self.client.force_login(self.gestor_a)

        response = self.client.get(reverse("financeiro"), self.parametros)

        self.assertNotContains(response, "500,00")
        self.assertNotContains(response, "999,00")
        self.assertNotContains(response, "Serviço externo")

    def test_recepcionista_e_barbeiro_nao_acessam_financeiro(self):
        recepcionista = Usuario.objects.create_user(
            username="recepcao_financeiro",
            password="senha-forte-123",
            barbearia=self.barbearia_a,
            papel=Usuario.Papel.RECEPCIONISTA,
        )
        for usuario in [recepcionista, self.barbeiro_a]:
            self.client.force_login(usuario)
            response = self.client.get(reverse("financeiro"), self.parametros)
            self.assertEqual(response.status_code, 403)

    def test_periodo_invalido_exibe_erro_sem_dados(self):
        self.client.force_login(self.gestor_a)

        response = self.client.get(
            reverse("financeiro"),
            {
                "data_inicio": self.data_fim.isoformat(),
                "data_fim": self.data_inicio.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A data final deve ser igual ou posterior")
        self.assertEqual(response.context["faturamento"], Decimal("0.00"))

    def test_exportacao_csv_respeita_filtros_e_formato_brasileiro(self):
        self.client.force_login(self.gestor_a)
        parametros = {**self.parametros, "profissional": self.barbeiro_a.pk}

        response = self.client.get(reverse("financeiro_exportar"), parametros)
        conteudo = response.content.decode("utf-8-sig")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Faturamento (R$);Comissão (R$);Líquido (R$)", conteudo)
        self.assertIn(";50,00;20,00;30,00", conteudo)
        self.assertNotIn(self.colega.nome_exibicao, conteudo)


class NotificacoesWhatsAppTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.cliente_a.telefone = "(32) 99999-1234"
        self.cliente_a.aceita_notificacoes_whatsapp = True
        self.cliente_a.save()
        self.inicio = timezone.now().replace(second=0, microsecond=0) + timedelta(
            days=3
        )
        self.agendamento = Agendamento.objects.create(
            barbearia=self.barbearia_a,
            cliente=self.cliente_a,
            profissional=self.barbeiro_a,
            servico=self.servico_a,
            inicio=self.inicio,
        )

    @override_settings(WHATSAPP_REMINDER_HOURS=(24, 2))
    def test_cria_confirmacao_e_dois_lembretes_com_numero_brasileiro(self):
        notificacoes = sincronizar_notificacoes(
            self.agendamento,
            incluir_confirmacao=True,
        )

        self.assertEqual(len(notificacoes), 3)
        self.assertEqual(
            set(
                NotificacaoWhatsApp.objects.filter(
                    agendamento=self.agendamento
                ).values_list("tipo", flat=True)
            ),
            {
                NotificacaoWhatsApp.Tipo.CONFIRMACAO,
                NotificacaoWhatsApp.Tipo.LEMBRETE_24H,
                NotificacaoWhatsApp.Tipo.LEMBRETE_2H,
            },
        )
        self.assertFalse(
            NotificacaoWhatsApp.objects.filter(
                agendamento=self.agendamento
            ).exclude(destinatario="5532999991234").exists()
        )

    def test_nao_cria_fila_sem_consentimento(self):
        self.cliente_a.aceita_notificacoes_whatsapp = False
        self.cliente_a.save(update_fields=["aceita_notificacoes_whatsapp"])

        notificacoes = sincronizar_notificacoes(
            self.agendamento,
            incluir_confirmacao=True,
        )

        self.assertEqual(notificacoes, [])
        self.assertFalse(NotificacaoWhatsApp.objects.exists())

    @override_settings(WHATSAPP_REMINDER_HOURS=(24, 2))
    def test_reagenda_lembretes_quando_horario_muda(self):
        sincronizar_notificacoes(self.agendamento, incluir_confirmacao=True)
        lembrete = NotificacaoWhatsApp.objects.get(
            agendamento=self.agendamento,
            tipo=NotificacaoWhatsApp.Tipo.LEMBRETE_24H,
        )
        horario_anterior = lembrete.agendada_para
        self.agendamento.inicio += timedelta(days=1)
        self.agendamento.save()

        sincronizar_notificacoes(self.agendamento)
        lembrete.refresh_from_db()

        self.assertEqual(
            lembrete.agendada_para,
            horario_anterior + timedelta(days=1),
        )
        self.assertEqual(lembrete.tentativas, 0)

    def test_cancelamento_remove_mensagens_pendentes(self):
        sincronizar_notificacoes(self.agendamento, incluir_confirmacao=True)

        cancelar_notificacoes(self.agendamento)

        self.assertFalse(
            NotificacaoWhatsApp.objects.filter(
                agendamento=self.agendamento,
                status=NotificacaoWhatsApp.Status.PENDENTE,
            ).exists()
        )

    @override_settings(
        WHATSAPP_ENABLED=True,
        WHATSAPP_DRY_RUN=True,
        WHATSAPP_REMINDER_HOURS=(24, 2),
        WHATSAPP_MAX_RETRIES=3,
    )
    def test_comando_processa_confirmacao_em_modo_simulacao(self):
        sincronizar_notificacoes(self.agendamento, incluir_confirmacao=True)
        saida = StringIO()

        call_command("processar_notificacoes_whatsapp", stdout=saida)

        confirmacao = NotificacaoWhatsApp.objects.get(
            agendamento=self.agendamento,
            tipo=NotificacaoWhatsApp.Tipo.CONFIRMACAO,
        )
        self.assertEqual(confirmacao.status, NotificacaoWhatsApp.Status.ENVIADA)
        self.assertEqual(confirmacao.tentativas, 1)
        self.assertEqual(confirmacao.mensagem_id, f"dry-run-{confirmacao.pk}")
        self.assertIn("1 enviada", saida.getvalue())

    @override_settings(
        WHATSAPP_ENABLED=True,
        WHATSAPP_DRY_RUN=True,
        WHATSAPP_REMINDER_HOURS=(24, 2),
        WHATSAPP_MAX_RETRIES=3,
    )
    def test_falha_de_envio_fica_registrada_para_nova_tentativa(self):
        sincronizar_notificacoes(self.agendamento, incluir_confirmacao=True)

        with patch(
            "gestao.management.commands.processar_notificacoes_whatsapp.enviar_notificacao",
            side_effect=WhatsAppErro("Falha simulada"),
        ):
            call_command("processar_notificacoes_whatsapp", stdout=StringIO())

        confirmacao = NotificacaoWhatsApp.objects.get(
            agendamento=self.agendamento,
            tipo=NotificacaoWhatsApp.Tipo.CONFIRMACAO,
        )
        self.assertEqual(confirmacao.status, NotificacaoWhatsApp.Status.FALHOU)
        self.assertEqual(confirmacao.tentativas, 1)
        self.assertIn("Falha simulada", confirmacao.ultimo_erro)

    @override_settings(WHATSAPP_REMINDER_HOURS=(24, 2))
    def test_agendamento_publico_registra_consentimento_e_fila(self):
        data = timezone.localdate() + timedelta(days=2)
        HorarioTrabalho.objects.create(
            barbearia=self.barbearia_a,
            profissional=self.barbeiro_a,
            dia_semana=data.weekday(),
            inicio=time(9, 0),
            fim=time(12, 0),
        )

        response = self.client.post(
            reverse("agendamento_publico", args=[self.barbearia_a.slug]),
            {
                "nome": "Cliente WhatsApp",
                "telefone": "(32) 98888-7777",
                "email": "",
                "servico": self.servico_a.pk,
                "profissional": self.barbeiro_a.pk,
                "data": data.isoformat(),
                "horario": "09:00",
                "confirmacao_dados": "on",
                "aceita_notificacoes_whatsapp": "on",
                "website": "",
            },
        )

        cliente = Cliente.objects.get(telefone="32988887777")
        agendamento = Agendamento.objects.get(cliente=cliente)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(cliente.aceita_notificacoes_whatsapp)
        self.assertTrue(
            NotificacaoWhatsApp.objects.filter(
                agendamento=agendamento,
                tipo=NotificacaoWhatsApp.Tipo.CONFIRMACAO,
            ).exists()
        )


class InfraestruturaProducaoTests(TestCase):
    def test_health_check_confirma_acesso_ao_banco(self):
        response = self.client.get(reverse("saude"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
