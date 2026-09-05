from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    Agendamento,
    Barbearia,
    BloqueioAgenda,
    Cliente,
    HorarioTrabalho,
    Servico,
    NotificacaoWhatsApp,
    Assinatura,
    Plano,
    Usuario,
)


@admin.register(Plano)
class PlanoAdmin(admin.ModelAdmin):
    list_display = ("nome", "codigo", "valor_mensal", "limite_profissionais", "ativo")
    list_filter = ("ativo",)
    search_fields = ("nome", "codigo")


@admin.register(Assinatura)
class AssinaturaAdmin(admin.ModelAdmin):
    list_display = ("barbearia", "plano", "status", "fim_teste", "fim_periodo_atual")
    list_filter = ("status", "plano")
    search_fields = ("barbearia__nome", "barbearia__email", "identificador_externo")
    autocomplete_fields = ("barbearia", "plano")


@admin.register(Barbearia)
class BarbeariaAdmin(admin.ModelAdmin):
    list_display = ("nome", "telefone", "email", "ativa", "criada_em")
    list_filter = ("ativa",)
    search_fields = ("nome", "telefone", "email")
    prepopulated_fields = {"slug": ("nome",)}


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "nome_exibicao", "barbearia", "papel", "is_active")
    list_filter = ("barbearia", "papel", "is_active", "is_staff")
    fieldsets = UserAdmin.fieldsets + (
        (
            "Dados da barbearia",
            {"fields": ("barbearia", "papel", "telefone", "especialidades", "foto_url", "comissao_percentual")},
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Dados da barbearia",
            {"fields": ("barbearia", "papel", "telefone", "especialidades", "foto_url", "comissao_percentual")},
        ),
    )


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = (
        "nome",
        "barbearia",
        "telefone",
        "email",
        "aceita_notificacoes_whatsapp",
        "ativo",
    )
    list_filter = ("barbearia", "aceita_notificacoes_whatsapp", "ativo")
    search_fields = ("nome", "telefone", "email")


@admin.register(Servico)
class ServicoAdmin(admin.ModelAdmin):
    list_display = ("nome", "barbearia", "duracao_minutos", "preco", "ativo")
    list_filter = ("barbearia", "ativo")
    search_fields = ("nome",)


@admin.register(Agendamento)
class AgendamentoAdmin(admin.ModelAdmin):
    list_display = (
        "inicio",
        "cliente",
        "profissional",
        "servico",
        "status",
        "origem",
        "forma_pagamento",
        "preco_cobrado",
        "comissao_valor",
    )
    list_filter = (
        "barbearia",
        "status",
        "origem",
        "forma_pagamento",
        "profissional",
    )
    search_fields = ("cliente__nome", "profissional__username", "servico__nome")
    autocomplete_fields = ("cliente", "profissional", "servico")


@admin.register(HorarioTrabalho)
class HorarioTrabalhoAdmin(admin.ModelAdmin):
    list_display = ("profissional", "barbearia", "dia_semana", "inicio", "fim", "ativo")
    list_filter = ("barbearia", "dia_semana", "ativo")
    autocomplete_fields = ("profissional",)


@admin.register(BloqueioAgenda)
class BloqueioAgendaAdmin(admin.ModelAdmin):
    list_display = ("profissional", "barbearia", "inicio", "fim", "motivo")
    list_filter = ("barbearia", "profissional")
    autocomplete_fields = ("profissional",)


@admin.register(NotificacaoWhatsApp)
class NotificacaoWhatsAppAdmin(admin.ModelAdmin):
    list_display = (
        "agendada_para",
        "tipo",
        "destinatario",
        "agendamento",
        "status",
        "tentativas",
    )
    list_filter = ("barbearia", "tipo", "status")
    search_fields = (
        "destinatario",
        "agendamento__cliente__nome",
        "mensagem_id",
    )
    readonly_fields = (
        "tentativas",
        "enviada_em",
        "mensagem_id",
        "ultimo_erro",
        "criada_em",
        "atualizada_em",
    )
