from django.urls import path

from . import views


urlpatterns = [
    path("assinatura/", views.assinatura_status, name="assinatura_status"),
    path(
        "agendar/<slug:slug>/",
        views.agendamento_publico,
        name="agendamento_publico",
    ),
    path(
        "agendar/<slug:slug>/horarios/",
        views.horarios_disponiveis_publico,
        name="horarios_disponiveis_publico",
    ),
    path(
        "agendar/<slug:slug>/confirmacao/",
        views.agendamento_publico_confirmacao,
        name="agendamento_publico_confirmacao",
    ),
    path("agendar/<slug:slug>/privacidade/", views.politica_privacidade_publica, name="politica_privacidade_publica"),
    path("agendar/<slug:slug>/reserva/<uuid:token>/", views.agendamento_publico_gerenciar, name="agendamento_publico_gerenciar"),
    path("agendar/<slug:slug>/reserva/<uuid:token>/cancelar/", views.agendamento_publico_cancelar, name="agendamento_publico_cancelar"),
    path("agendar/<slug:slug>/reserva/<uuid:token>/reagendar/", views.agendamento_publico_reagendar, name="agendamento_publico_reagendar"),
    path("", views.dashboard, name="dashboard"),
    path("meu-dia/", views.meu_dia, name="meu_dia"),
    path(
        "meu-dia/<int:pk>/confirmar-chegada/",
        views.atendimento_confirmar_chegada,
        name="atendimento_confirmar_chegada",
    ),
    path(
        "meu-dia/<int:pk>/iniciar/",
        views.atendimento_iniciar,
        name="atendimento_iniciar",
    ),
    path(
        "meu-dia/<int:pk>/registrar-falta/",
        views.atendimento_registrar_falta,
        name="atendimento_registrar_falta",
    ),
    path(
        "meu-dia/<int:pk>/concluir/",
        views.atendimento_concluir,
        name="atendimento_concluir",
    ),
    path("agenda/", views.agenda_visual, name="agenda_visual"),
    path("financeiro/", views.financeiro, name="financeiro"),
    path("configuracao-publica/", views.configuracao_publica, name="configuracao_publica"),
    path(
        "financeiro/exportar/",
        views.financeiro_exportar,
        name="financeiro_exportar",
    ),
    path("equipe/", views.equipe_lista, name="equipe_lista"),
    path(
        "equipe/novo/",
        views.funcionario_criar,
        name="funcionario_criar",
    ),
    path(
        "equipe/<int:pk>/editar/",
        views.funcionario_editar,
        name="funcionario_editar",
    ),
    path(
        "equipe/<int:pk>/alterar-status/",
        views.funcionario_alterar_status,
        name="funcionario_alterar_status",
    ),
    path(
        "equipe/<int:profissional_pk>/disponibilidade/",
        views.disponibilidade_profissional,
        name="disponibilidade_profissional",
    ),
    path(
        "equipe/<int:profissional_pk>/horarios/novo/",
        views.horario_trabalho_criar,
        name="horario_trabalho_criar",
    ),
    path(
        "equipe/<int:profissional_pk>/horarios/<int:pk>/editar/",
        views.horario_trabalho_editar,
        name="horario_trabalho_editar",
    ),
    path(
        "equipe/<int:profissional_pk>/horarios/<int:pk>/excluir/",
        views.horario_trabalho_excluir,
        name="horario_trabalho_excluir",
    ),
    path(
        "equipe/<int:profissional_pk>/bloqueios/novo/",
        views.bloqueio_agenda_criar,
        name="bloqueio_agenda_criar",
    ),
    path(
        "equipe/<int:profissional_pk>/bloqueios/<int:pk>/editar/",
        views.bloqueio_agenda_editar,
        name="bloqueio_agenda_editar",
    ),
    path(
        "equipe/<int:profissional_pk>/bloqueios/<int:pk>/excluir/",
        views.bloqueio_agenda_excluir,
        name="bloqueio_agenda_excluir",
    ),
    path("clientes/", views.ClienteListaView.as_view(), name="cliente_lista"),
    path("clientes/novo/", views.ClienteCriarView.as_view(), name="cliente_criar"),
    path(
        "clientes/<int:pk>/editar/",
        views.ClienteEditarView.as_view(),
        name="cliente_editar",
    ),
    path("servicos/", views.ServicoListaView.as_view(), name="servico_lista"),
    path("servicos/novo/", views.ServicoCriarView.as_view(), name="servico_criar"),
    path(
        "servicos/<int:pk>/editar/",
        views.ServicoEditarView.as_view(),
        name="servico_editar",
    ),
    path(
        "agendamentos/",
        views.AgendamentoListaView.as_view(),
        name="agendamento_lista",
    ),
    path(
        "agendamentos/novo/",
        views.AgendamentoCriarView.as_view(),
        name="agendamento_criar",
    ),
    path(
        "agendamentos/<int:pk>/editar/",
        views.AgendamentoEditarView.as_view(),
        name="agendamento_editar",
    ),
    path(
        "agendamentos/<int:pk>/cancelar/",
        views.cancelar_agendamento,
        name="agendamento_cancelar",
    ),
]
