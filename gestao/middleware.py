from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.deprecation import MiddlewareMixin

from .assinaturas import barbearia_tem_acesso, obter_assinatura
from .models import Barbearia


class AcessoAssinaturaMiddleware(MiddlewareMixin):
    """Aplica a assinatura em cada acesso, inclusive nos endpoints públicos."""

    ROTAS_PUBLICAS_BLOQUEADAS = {
        "agendamento_publico",
        "horarios_disponiveis_publico",
    }
    ROTAS_SEMPRE_LIBERADAS = {
        "assinatura_status",
        "login",
        "logout",
        "saude",
        "politica_privacidade_publica",
        "agendamento_publico_confirmacao",
        "agendamento_publico_gerenciar",
        "agendamento_publico_cancelar",
        "agendamento_publico_reagendar",
    }

    def process_view(self, request, view_func, view_args, view_kwargs):
        rota = request.resolver_match.view_name

        if rota in self.ROTAS_PUBLICAS_BLOQUEADAS:
            barbearia = get_object_or_404(
                Barbearia,
                slug=view_kwargs.get("slug"),
                ativa=True,
            )
            if not barbearia_tem_acesso(barbearia):
                if rota == "horarios_disponiveis_publico":
                    return JsonResponse(
                        {"erro": "Agendamento temporariamente indisponível."},
                        status=403,
                    )
                return render(
                    request,
                    "gestao/agendamento_publico_suspenso.html",
                    {"barbearia": barbearia},
                    status=403,
                )
            return None

        if rota in self.ROTAS_SEMPRE_LIBERADAS or rota.startswith("admin:"):
            return None
        if not request.user.is_authenticated or request.user.is_superuser:
            return None
        if not request.user.barbearia_id:
            return None

        assinatura = obter_assinatura(request.user.barbearia)
        if not assinatura or not assinatura.acesso_liberado():
            return redirect("assinatura_status")
        return None
