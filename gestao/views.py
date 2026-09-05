import csv
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.generic import CreateView, ListView, UpdateView

from .forms import (
    AgendamentoForm,
    AgendamentoPublicoForm,
    BloqueioAgendaForm,
    ClienteForm,
    ConclusaoAtendimentoForm,
    FinanceiroFiltroForm,
    ConfiguracaoPublicaForm,
    FuncionarioCriacaoForm,
    FuncionarioEdicaoForm,
    HorarioTrabalhoForm,
    ReagendamentoPublicoForm,
    ServicoForm,
)
from .mixins import (
    FormDaBarbeariaMixin,
    GestorObrigatorioMixin,
    QuerysetDaBarbeariaMixin,
)
from .models import (
    Agendamento,
    Assinatura,
    Barbearia,
    BloqueioAgenda,
    Cliente,
    HorarioTrabalho,
    Servico,
    Usuario,
)
from .assinaturas import obter_assinatura
from .services import horarios_disponiveis
from .whatsapp import cancelar_notificacoes, sincronizar_notificacoes


NOMES_DIAS_SEMANA = (
    "Segunda",
    "Terça",
    "Quarta",
    "Quinta",
    "Sexta",
    "Sábado",
    "Domingo",
)


@login_required
def assinatura_status(request):
    if not request.user.barbearia_id:
        raise PermissionDenied("Seu usuário não está vinculado a uma barbearia.")
    assinatura = obter_assinatura(request.user.barbearia)
    return render(
        request,
        "gestao/assinatura_status.html",
        {
            "assinatura": assinatura,
            "assinatura_sem_acesso": not assinatura or not assinatura.acesso_liberado(),
            "dias_restantes": assinatura.dias_restantes_teste() if assinatura else 0,
            "eh_proprietario": request.user.papel == Usuario.Papel.PROPRIETARIO,
        },
    )


def _limite_publico_excedido(request, acao, limite, periodo):
    """Limite simples por IP; funciona também com Redis em produção."""
    ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
    ip = ip or request.META.get("REMOTE_ADDR", "desconhecido")
    chave = f"publico:{acao}:{ip}"
    if cache.add(chave, 1, periodo):
        return False
    try:
        return cache.incr(chave) > limite
    except ValueError:
        cache.set(chave, 1, periodo)
        return False


def _telefone_href(telefone):
    digitos = "".join(caractere for caractere in (telefone or "") if caractere.isdigit())
    if not digitos:
        return ""
    if len(digitos) in {10, 11}:
        digitos = f"55{digitos}"
    return f"https://wa.me/{digitos}"


@login_required
def dashboard(request):
    if not request.user.barbearia_id:
        raise PermissionDenied("Seu usuário não está vinculado a uma barbearia.")
    if request.user.papel == Usuario.Papel.BARBEIRO and not request.user.is_superuser:
        return redirect("meu_dia")

    hoje = timezone.localdate()
    inicio_dia = timezone.make_aware(datetime.combine(hoje, time.min))
    fim_dia = inicio_dia + timedelta(days=1)
    base = Agendamento.objects.filter(barbearia=request.user.barbearia)
    agendamentos_hoje = base.filter(inicio__gte=inicio_dia, inicio__lt=fim_dia)
    concluidos_hoje = agendamentos_hoje.filter(status=Agendamento.Status.CONCLUIDO)

    contexto = {
        "agendamentos_hoje": agendamentos_hoje.select_related(
            "cliente", "profissional", "servico"
        ),
        "total_hoje": agendamentos_hoje.exclude(
            status=Agendamento.Status.CANCELADO
        ).count(),
        "clientes_ativos": Cliente.objects.filter(
            barbearia=request.user.barbearia,
            ativo=True,
        ).count(),
        "faturamento_hoje": concluidos_hoje.aggregate(total=Sum("preco_cobrado"))[
            "total"
        ]
        or 0,
        "url_agendamento_publico": request.build_absolute_uri(
            reverse("agendamento_publico", args=[request.user.barbearia.slug])
        ),
    }
    return render(request, "gestao/dashboard.html", contexto)


def _exigir_barbeiro(request):
    if not request.user.barbearia_id:
        raise PermissionDenied("Seu usuário não está vinculado a uma barbearia.")
    if request.user.papel != Usuario.Papel.BARBEIRO:
        raise PermissionDenied("Esta área é exclusiva dos barbeiros.")


def _obter_atendimento_do_barbeiro(request, pk, bloquear=False):
    queryset = Agendamento.objects.select_related("cliente", "servico", "profissional")
    if bloquear:
        queryset = queryset.select_for_update()
    return get_object_or_404(
        queryset,
        pk=pk,
        barbearia=request.user.barbearia,
        profissional=request.user,
        inicio__date=timezone.localdate(),
    )


@login_required
def meu_dia(request):
    _exigir_barbeiro(request)
    hoje = timezone.localdate()
    inicio_dia = timezone.make_aware(datetime.combine(hoje, time.min))
    fim_dia = inicio_dia + timedelta(days=1)
    agendamentos = list(
        Agendamento.objects.filter(
            barbearia=request.user.barbearia,
            profissional=request.user,
            inicio__gte=inicio_dia,
            inicio__lt=fim_dia,
        )
        .select_related("cliente", "servico")
        .order_by("inicio")
    )
    agora = timezone.now()
    estados_ativos = {
        Agendamento.Status.AGENDADO,
        Agendamento.Status.CONFIRMADO,
        Agendamento.Status.EM_ATENDIMENTO,
    }
    proximo = next(
        (
            item
            for item in agendamentos
            if item.status == Agendamento.Status.EM_ATENDIMENTO
        ),
        None,
    )
    if proximo is None:
        proximo = next(
            (
                item
                for item in agendamentos
                if item.status in estados_ativos and item.inicio >= agora
            ),
            None,
        )
    if proximo is None:
        proximo = next(
            (item for item in agendamentos if item.status in estados_ativos),
            None,
        )

    concluidos = [
        item for item in agendamentos if item.status == Agendamento.Status.CONCLUIDO
    ]
    contexto = {
        "agendamentos": agendamentos,
        "proximo": proximo,
        "hoje": hoje,
        "total_hoje": len(
            [
                item
                for item in agendamentos
                if item.status != Agendamento.Status.CANCELADO
            ]
        ),
        "total_concluidos": len(concluidos),
        "total_pendentes": len(
            [item for item in agendamentos if item.status in estados_ativos]
        ),
        "comissao_hoje": sum(
            (item.comissao_valor or 0 for item in concluidos),
            Decimal("0.00"),
        ),
    }
    return render(request, "gestao/meu_dia.html", contexto)


@login_required
@require_POST
def atendimento_confirmar_chegada(request, pk):
    _exigir_barbeiro(request)
    with transaction.atomic():
        agendamento = _obter_atendimento_do_barbeiro(request, pk, bloquear=True)
        if agendamento.status != Agendamento.Status.AGENDADO:
            messages.error(request, "Este atendimento não pode mais ser confirmado.")
        else:
            agendamento.status = Agendamento.Status.CONFIRMADO
            agendamento.save(update_fields=["status", "atualizado_em"])
            messages.success(request, "Chegada do cliente confirmada.")
    return redirect("meu_dia")


@login_required
@require_POST
def atendimento_iniciar(request, pk):
    _exigir_barbeiro(request)
    with transaction.atomic():
        agendamento = _obter_atendimento_do_barbeiro(request, pk, bloquear=True)
        if agendamento.status != Agendamento.Status.CONFIRMADO:
            messages.error(request, "Confirme a chegada do cliente antes de iniciar.")
        else:
            agendamento.status = Agendamento.Status.EM_ATENDIMENTO
            agendamento.iniciado_em = timezone.now()
            agendamento.save(
                update_fields=["status", "iniciado_em", "atualizado_em"]
            )
            messages.success(request, "Atendimento iniciado.")
    return redirect("meu_dia")


@login_required
@require_POST
def atendimento_registrar_falta(request, pk):
    _exigir_barbeiro(request)
    with transaction.atomic():
        agendamento = _obter_atendimento_do_barbeiro(request, pk, bloquear=True)
        if agendamento.status not in {
            Agendamento.Status.AGENDADO,
            Agendamento.Status.CONFIRMADO,
        }:
            messages.error(request, "Não é possível registrar falta neste atendimento.")
        else:
            agendamento.status = Agendamento.Status.FALTOU
            agendamento.save(update_fields=["status", "atualizado_em"])
            cancelar_notificacoes(agendamento)
            messages.success(request, "Falta registrada.")
    return redirect("meu_dia")


@login_required
@require_http_methods(["GET", "POST"])
def atendimento_concluir(request, pk):
    _exigir_barbeiro(request)
    agendamento = _obter_atendimento_do_barbeiro(request, pk)
    if agendamento.status != Agendamento.Status.EM_ATENDIMENTO:
        messages.error(request, "Inicie o atendimento antes de concluí-lo.")
        return redirect("meu_dia")

    form = ConclusaoAtendimentoForm(
        request.POST or None,
        agendamento=agendamento,
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            agendamento = _obter_atendimento_do_barbeiro(request, pk, bloquear=True)
            if agendamento.status != Agendamento.Status.EM_ATENDIMENTO:
                messages.error(request, "Este atendimento já foi atualizado.")
                return redirect("meu_dia")
            agendamento.preco_cobrado = form.cleaned_data["preco_cobrado"]
            agendamento.forma_pagamento = form.cleaned_data["forma_pagamento"]
            agendamento.status = Agendamento.Status.CONCLUIDO
            agendamento.concluido_em = timezone.now()
            agendamento.comissao_percentual_aplicada = (
                agendamento.profissional.comissao_percentual
            )
            agendamento.comissao_valor = None
            agendamento.save()
            cancelar_notificacoes(agendamento)
        messages.success(request, "Atendimento concluído e comissão registrada.")
        return redirect("meu_dia")

    comissao_estimada = (
        (agendamento.preco_cobrado or 0)
        * request.user.comissao_percentual
        / 100
    )
    return render(
        request,
        "gestao/concluir_atendimento.html",
        {
            "agendamento": agendamento,
            "form": form,
            "comissao_estimada": comissao_estimada,
        },
    )


def _url_agenda_visual(**parametros):
    parametros_validos = {
        chave: valor for chave, valor in parametros.items() if valor not in (None, "")
    }
    query = urlencode(parametros_validos)
    return f"{reverse('agenda_visual')}?{query}" if query else reverse("agenda_visual")


def _exigir_proprietario(request):
    if not request.user.barbearia_id:
        raise PermissionDenied("Seu usuário não está vinculado a uma barbearia.")
    if not request.user.is_superuser and request.user.papel != Usuario.Papel.PROPRIETARIO:
        raise PermissionDenied("Esta área é exclusiva do proprietário.")


def _consulta_financeira(request):
    hoje = timezone.localdate()
    parametros = request.GET or {
        "data_inicio": hoje.replace(day=1).isoformat(),
        "data_fim": hoje.isoformat(),
    }
    form = FinanceiroFiltroForm(
        parametros,
        barbearia=request.user.barbearia,
    )
    queryset = Agendamento.objects.none()
    if form.is_valid():
        data_inicio = form.cleaned_data["data_inicio"]
        data_fim = form.cleaned_data["data_fim"]
        inicio = timezone.make_aware(datetime.combine(data_inicio, time.min))
        fim = timezone.make_aware(
            datetime.combine(data_fim + timedelta(days=1), time.min)
        )
        queryset = Agendamento.objects.filter(
            barbearia=request.user.barbearia,
            status=Agendamento.Status.CONCLUIDO,
            inicio__gte=inicio,
            inicio__lt=fim,
        )
        profissional = form.cleaned_data.get("profissional")
        if profissional:
            queryset = queryset.filter(profissional=profissional)
        forma_pagamento = form.cleaned_data.get("forma_pagamento")
        if forma_pagamento == FinanceiroFiltroForm.PAGAMENTO_NAO_INFORMADO:
            queryset = queryset.filter(forma_pagamento="")
        elif forma_pagamento:
            queryset = queryset.filter(forma_pagamento=forma_pagamento)
    return form, queryset


def _nome_profissional(registro):
    nome_completo = " ".join(
        parte
        for parte in [
            registro["profissional__first_name"],
            registro["profissional__last_name"],
        ]
        if parte
    )
    return nome_completo or registro["profissional__username"]


@login_required
def financeiro(request):
    _exigir_proprietario(request)
    form, queryset = _consulta_financeira(request)
    resumo = queryset.aggregate(
        faturamento=Sum("preco_cobrado"),
        comissoes=Sum("comissao_valor"),
        atendimentos=Count("id"),
    )
    faturamento = resumo["faturamento"] or Decimal("0.00")
    comissoes = resumo["comissoes"] or Decimal("0.00")
    atendimentos = resumo["atendimentos"] or 0
    ticket_medio = (
        (faturamento / atendimentos).quantize(Decimal("0.01"))
        if atendimentos
        else Decimal("0.00")
    )

    rotulos_pagamento = dict(Agendamento.FormaPagamento.choices)
    pagamentos = []
    for item in queryset.values("forma_pagamento").annotate(
        total=Sum("preco_cobrado"),
        quantidade=Count("id"),
    ).order_by("-total"):
        total = item["total"] or Decimal("0.00")
        pagamentos.append(
            {
                "valor": item["forma_pagamento"],
                "nome": rotulos_pagamento.get(
                    item["forma_pagamento"],
                    "Não informado",
                ),
                "total": total,
                "quantidade": item["quantidade"],
                "percentual": (
                    (total / faturamento * 100).quantize(Decimal("0.1"))
                    if faturamento
                    else Decimal("0.0")
                ),
            }
        )

    comissoes_profissionais = []
    for item in queryset.values(
        "profissional_id",
        "profissional__first_name",
        "profissional__last_name",
        "profissional__username",
    ).annotate(
        faturamento=Sum("preco_cobrado"),
        comissao=Sum("comissao_valor"),
        atendimentos=Count("id"),
    ).order_by("-faturamento"):
        total_profissional = item["faturamento"] or Decimal("0.00")
        comissao_profissional = item["comissao"] or Decimal("0.00")
        comissoes_profissionais.append(
            {
                "nome": _nome_profissional(item),
                "atendimentos": item["atendimentos"],
                "faturamento": total_profissional,
                "comissao": comissao_profissional,
                "liquido": total_profissional - comissao_profissional,
                "taxa_efetiva": (
                    (comissao_profissional / total_profissional * 100).quantize(
                        Decimal("0.1")
                    )
                    if total_profissional
                    else Decimal("0.0")
                ),
            }
        )

    faturamento_diario = list(
        queryset.annotate(
            dia=TruncDate("inicio", tzinfo=timezone.get_current_timezone())
        )
        .values("dia")
        .annotate(total=Sum("preco_cobrado"), quantidade=Count("id"))
        .order_by("dia")
    )
    maior_dia = max(
        (item["total"] or Decimal("0.00") for item in faturamento_diario),
        default=Decimal("0.00"),
    )
    for item in faturamento_diario:
        item["percentual"] = (
            ((item["total"] or 0) / maior_dia * 100).quantize(Decimal("0.1"))
            if maior_dia
            else Decimal("0.0")
        )

    contexto = {
        "form": form,
        "faturamento": faturamento,
        "comissoes": comissoes,
        "liquido": faturamento - comissoes,
        "atendimentos": atendimentos,
        "ticket_medio": ticket_medio,
        "pagamentos": pagamentos,
        "comissoes_profissionais": comissoes_profissionais,
        "faturamento_diario": faturamento_diario,
        "agendamentos_recentes": queryset.select_related(
            "cliente", "profissional", "servico"
        ).order_by("-inicio")[:50],
        "query_exportacao": request.GET.urlencode(),
    }
    return render(request, "gestao/financeiro.html", contexto)


@login_required
@require_GET
def financeiro_exportar(request):
    _exigir_proprietario(request)
    form, queryset = _consulta_financeira(request)
    if not form.is_valid():
        messages.error(request, "Corrija o período antes de exportar o relatório.")
        return redirect("financeiro")

    data_inicio = form.cleaned_data["data_inicio"]
    data_fim = form.cleaned_data["data_fim"]
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="financeiro-{data_inicio}-{data_fim}.csv"'
    )
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(
        [
            "Data",
            "Cliente",
            "Barbeiro",
            "Serviço",
            "Forma de pagamento",
            "Faturamento (R$)",
            "Comissão (R$)",
            "Líquido (R$)",
        ]
    )

    for agendamento in queryset.select_related(
        "cliente", "profissional", "servico"
    ).order_by("inicio"):
        faturamento_item = agendamento.preco_cobrado or Decimal("0.00")
        comissao_item = agendamento.comissao_valor or Decimal("0.00")
        writer.writerow(
            [
                timezone.localtime(agendamento.inicio).strftime("%d/%m/%Y %H:%M"),
                agendamento.cliente.nome,
                agendamento.profissional.nome_exibicao,
                agendamento.servico.nome,
                agendamento.get_forma_pagamento_display() or "Não informado",
                f"{faturamento_item:.2f}".replace(".", ","),
                f"{comissao_item:.2f}".replace(".", ","),
                f"{faturamento_item - comissao_item:.2f}".replace(".", ","),
            ]
        )
    return response


def _obter_barbeiro(request, profissional_pk):
    return get_object_or_404(
        Usuario,
        pk=profissional_pk,
        barbearia=request.user.barbearia,
        papel=Usuario.Papel.BARBEIRO,
    )


def _obter_funcionario(request, pk):
    return get_object_or_404(
        Usuario,
        pk=pk,
        barbearia=request.user.barbearia,
        papel__in=[Usuario.Papel.BARBEIRO, Usuario.Papel.RECEPCIONISTA],
    )


@login_required
def equipe_lista(request):
    _exigir_proprietario(request)
    profissionais = list(
        Usuario.objects.filter(
            barbearia=request.user.barbearia,
            papel__in=[Usuario.Papel.BARBEIRO, Usuario.Papel.RECEPCIONISTA],
        )
        .prefetch_related(
            Prefetch(
                "horarios_trabalho",
                queryset=HorarioTrabalho.objects.filter(ativo=True).order_by(
                    "dia_semana", "inicio"
                ),
                to_attr="horarios_ativos",
            ),
            Prefetch(
                "bloqueios_agenda",
                queryset=BloqueioAgenda.objects.filter(
                    fim__gte=timezone.now()
                ).order_by("inicio"),
                to_attr="bloqueios_futuros",
            ),
        )
        .order_by("first_name", "username")
    )
    return render(
        request,
        "gestao/equipe_lista.html",
        {"profissionais": profissionais},
    )


@login_required
def funcionario_criar(request):
    _exigir_proprietario(request)
    instancia = Usuario(
        barbearia=request.user.barbearia,
        papel=Usuario.Papel.BARBEIRO,
        is_active=True,
    )
    form = FuncionarioCriacaoForm(request.POST or None, instance=instancia)
    if request.method == "POST" and form.is_valid():
        funcionario = form.save(commit=False)
        funcionario.barbearia = request.user.barbearia
        funcionario.save()
        messages.success(request, "Funcionário cadastrado com sucesso.")
        return redirect("equipe_lista")
    return render(
        request,
        "gestao/funcionario_form.html",
        {
            "form": form,
            "titulo": "Novo funcionário",
            "subtitulo": "Crie o acesso de um barbeiro ou recepcionista.",
            "funcionario": None,
        },
    )


@login_required
def funcionario_editar(request, pk):
    _exigir_proprietario(request)
    funcionario = _obter_funcionario(request, pk)
    form = FuncionarioEdicaoForm(request.POST or None, instance=funcionario)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Funcionário atualizado com sucesso.")
        return redirect("equipe_lista")
    return render(
        request,
        "gestao/funcionario_form.html",
        {
            "form": form,
            "titulo": "Editar funcionário",
            "subtitulo": "Atualize os dados, a comissão ou a senha de acesso.",
            "funcionario": funcionario,
        },
    )


@login_required
def funcionario_alterar_status(request, pk):
    _exigir_proprietario(request)
    if request.method != "POST":
        return redirect("equipe_lista")
    funcionario = _obter_funcionario(request, pk)

    if funcionario.is_active:
        atendimentos_futuros = Agendamento.objects.filter(
            barbearia=request.user.barbearia,
            profissional=funcionario,
            inicio__gte=timezone.now(),
            status__in=[
                Agendamento.Status.AGENDADO,
                Agendamento.Status.CONFIRMADO,
            ],
        ).exists()
        if atendimentos_futuros:
            messages.error(
                request,
                "Este barbeiro possui atendimentos futuros. Cancele ou transfira esses horários antes de desativá-lo.",
            )
            return redirect("equipe_lista")

    funcionario.is_active = not funcionario.is_active
    funcionario.save(update_fields=["is_active"])
    situacao = "reativado" if funcionario.is_active else "desativado"
    messages.success(request, f"Funcionário {situacao} com sucesso.")
    return redirect("equipe_lista")


@login_required
def disponibilidade_profissional(request, profissional_pk):
    _exigir_proprietario(request)
    profissional = _obter_barbeiro(request, profissional_pk)
    horarios = list(
        HorarioTrabalho.objects.filter(
            barbearia=request.user.barbearia,
            profissional=profissional,
        ).order_by("dia_semana", "inicio")
    )
    horarios_por_dia = [
        {
            "valor": valor,
            "nome": nome,
            "horarios": [horario for horario in horarios if horario.dia_semana == valor],
        }
        for valor, nome in HorarioTrabalho.DiaSemana.choices
    ]
    bloqueios = BloqueioAgenda.objects.filter(
        barbearia=request.user.barbearia,
        profissional=profissional,
        fim__gte=timezone.now(),
    ).order_by("inicio")
    return render(
        request,
        "gestao/disponibilidade_profissional.html",
        {
            "profissional": profissional,
            "horarios_por_dia": horarios_por_dia,
            "bloqueios": bloqueios,
        },
    )


def _editar_horario(request, profissional, horario=None):
    instancia = horario or HorarioTrabalho(
        barbearia=request.user.barbearia,
        profissional=profissional,
    )
    form = HorarioTrabalhoForm(request.POST or None, instance=instancia)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Horário de trabalho salvo com sucesso.")
        return redirect("disponibilidade_profissional", profissional_pk=profissional.pk)
    return render(
        request,
        "gestao/disponibilidade_form.html",
        {
            "form": form,
            "profissional": profissional,
            "titulo": "Editar horário" if horario else "Novo horário de trabalho",
            "subtitulo": "Adicione dois períodos no mesmo dia para representar um intervalo.",
        },
    )


@login_required
def horario_trabalho_criar(request, profissional_pk):
    _exigir_proprietario(request)
    profissional = _obter_barbeiro(request, profissional_pk)
    return _editar_horario(request, profissional)


@login_required
def horario_trabalho_editar(request, profissional_pk, pk):
    _exigir_proprietario(request)
    profissional = _obter_barbeiro(request, profissional_pk)
    horario = get_object_or_404(
        HorarioTrabalho,
        pk=pk,
        barbearia=request.user.barbearia,
        profissional=profissional,
    )
    return _editar_horario(request, profissional, horario)


@login_required
def horario_trabalho_excluir(request, profissional_pk, pk):
    _exigir_proprietario(request)
    profissional = _obter_barbeiro(request, profissional_pk)
    horario = get_object_or_404(
        HorarioTrabalho,
        pk=pk,
        barbearia=request.user.barbearia,
        profissional=profissional,
    )
    if request.method == "POST":
        horario.delete()
        messages.success(request, "Horário de trabalho removido.")
        return redirect("disponibilidade_profissional", profissional_pk=profissional.pk)
    return render(
        request,
        "gestao/confirmar_exclusao.html",
        {
            "titulo": "Excluir horário",
            "descricao": str(horario),
            "voltar_href": reverse(
                "disponibilidade_profissional", args=[profissional.pk]
            ),
        },
    )


def _editar_bloqueio(request, profissional, bloqueio=None):
    instancia = bloqueio or BloqueioAgenda(
        barbearia=request.user.barbearia,
        profissional=profissional,
    )
    form = BloqueioAgendaForm(request.POST or None, instance=instancia)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Indisponibilidade salva com sucesso.")
        return redirect("disponibilidade_profissional", profissional_pk=profissional.pk)
    return render(
        request,
        "gestao/disponibilidade_form.html",
        {
            "form": form,
            "profissional": profissional,
            "titulo": "Editar indisponibilidade" if bloqueio else "Nova indisponibilidade",
            "subtitulo": "Use para folgas, férias, consultas ou compromissos pessoais.",
        },
    )


@login_required
def bloqueio_agenda_criar(request, profissional_pk):
    _exigir_proprietario(request)
    profissional = _obter_barbeiro(request, profissional_pk)
    return _editar_bloqueio(request, profissional)


@login_required
def bloqueio_agenda_editar(request, profissional_pk, pk):
    _exigir_proprietario(request)
    profissional = _obter_barbeiro(request, profissional_pk)
    bloqueio = get_object_or_404(
        BloqueioAgenda,
        pk=pk,
        barbearia=request.user.barbearia,
        profissional=profissional,
    )
    return _editar_bloqueio(request, profissional, bloqueio)


@login_required
def bloqueio_agenda_excluir(request, profissional_pk, pk):
    _exigir_proprietario(request)
    profissional = _obter_barbeiro(request, profissional_pk)
    bloqueio = get_object_or_404(
        BloqueioAgenda,
        pk=pk,
        barbearia=request.user.barbearia,
        profissional=profissional,
    )
    if request.method == "POST":
        bloqueio.delete()
        messages.success(request, "Indisponibilidade removida.")
        return redirect("disponibilidade_profissional", profissional_pk=profissional.pk)
    return render(
        request,
        "gestao/confirmar_exclusao.html",
        {
            "titulo": "Excluir indisponibilidade",
            "descricao": str(bloqueio),
            "voltar_href": reverse(
                "disponibilidade_profissional", args=[profissional.pk]
            ),
        },
    )


@login_required
def agenda_visual(request):
    if not request.user.barbearia_id:
        raise PermissionDenied("Seu usuário não está vinculado a uma barbearia.")

    modo = request.GET.get("modo", "dia")
    if modo not in {"dia", "semana"}:
        modo = "dia"

    try:
        data_selecionada = date.fromisoformat(request.GET.get("data", ""))
    except ValueError:
        data_selecionada = timezone.localdate()

    profissionais = Usuario.objects.filter(
        barbearia=request.user.barbearia,
        papel=Usuario.Papel.BARBEIRO,
        is_active=True,
    ).order_by("first_name", "username")
    profissional_selecionado = None
    if request.user.papel == Usuario.Papel.BARBEIRO and not request.user.is_superuser:
        profissionais = profissionais.filter(pk=request.user.pk)
        profissional_selecionado = request.user
    else:
        try:
            profissional_id = int(request.GET.get("profissional", ""))
        except (TypeError, ValueError):
            profissional_id = None
        if profissional_id:
            profissional_selecionado = profissionais.filter(pk=profissional_id).first()

    status_selecionado = request.GET.get("status", "")
    if status_selecionado not in Agendamento.Status.values:
        status_selecionado = ""

    if modo == "semana":
        inicio_periodo_data = data_selecionada - timedelta(
            days=data_selecionada.weekday()
        )
        fim_periodo_data = inicio_periodo_data + timedelta(days=7)
        passo_navegacao = timedelta(days=7)
    else:
        inicio_periodo_data = data_selecionada
        fim_periodo_data = data_selecionada + timedelta(days=1)
        passo_navegacao = timedelta(days=1)

    inicio_periodo = timezone.make_aware(
        datetime.combine(inicio_periodo_data, time.min)
    )
    fim_periodo = timezone.make_aware(datetime.combine(fim_periodo_data, time.min))
    queryset = (
        Agendamento.objects.filter(
            barbearia=request.user.barbearia,
            profissional__in=profissionais,
            inicio__lt=fim_periodo,
            fim__gt=inicio_periodo,
        )
        .select_related("cliente", "profissional", "servico")
        .order_by("inicio")
    )
    if profissional_selecionado:
        queryset = queryset.filter(profissional=profissional_selecionado)
    if status_selecionado:
        queryset = queryset.filter(status=status_selecionado)
    agendamentos = list(queryset)

    parametros_comuns = {
        "modo": modo,
        "profissional": (
            profissional_selecionado.pk
            if profissional_selecionado and request.user.pode_gerenciar
            else ""
        ),
        "status": status_selecionado,
    }
    contexto = {
        "modo": modo,
        "data_selecionada": data_selecionada,
        "profissionais": profissionais,
        "profissional_selecionado": profissional_selecionado,
        "status_selecionado": status_selecionado,
        "status_opcoes": Agendamento.Status.choices,
        "total_agendamentos": len(agendamentos),
        "url_anterior": _url_agenda_visual(
            **parametros_comuns,
            data=(data_selecionada - passo_navegacao).isoformat(),
        ),
        "url_proximo": _url_agenda_visual(
            **parametros_comuns,
            data=(data_selecionada + passo_navegacao).isoformat(),
        ),
        "url_hoje": _url_agenda_visual(
            **parametros_comuns,
            data=timezone.localdate().isoformat(),
        ),
        "url_modo_dia": _url_agenda_visual(
            **{**parametros_comuns, "modo": "dia"},
            data=data_selecionada.isoformat(),
        ),
        "url_modo_semana": _url_agenda_visual(
            **{**parametros_comuns, "modo": "semana"},
            data=data_selecionada.isoformat(),
        ),
        "url_limpar_filtros": _url_agenda_visual(
            modo=modo,
            data=data_selecionada.isoformat(),
        ),
    }

    if modo == "dia":
        escala_minuto = 1.5
        minutos_inicio = 7 * 60
        minutos_fim = 20 * 60
        horarios_observados = []
        for agendamento in agendamentos:
            inicio_local = timezone.localtime(agendamento.inicio)
            fim_local = timezone.localtime(agendamento.fim)
            horarios_observados.extend(
                [
                    inicio_local.hour * 60 + inicio_local.minute,
                    fim_local.hour * 60 + fim_local.minute,
                ]
            )
        if horarios_observados:
            minutos_inicio = min(minutos_inicio, (min(horarios_observados) // 60) * 60)
            minutos_fim = max(
                minutos_fim,
                ((max(horarios_observados) + 59) // 60) * 60,
            )
        minutos_inicio = max(0, minutos_inicio)
        minutos_fim = min(24 * 60, minutos_fim)

        profissionais_exibidos = (
            [profissional_selecionado]
            if profissional_selecionado
            else list(profissionais)
        )
        colunas = []
        for profissional in profissionais_exibidos:
            cards = []
            for agendamento in agendamentos:
                if agendamento.profissional_id != profissional.pk:
                    continue
                inicio_local = timezone.localtime(agendamento.inicio)
                fim_local = timezone.localtime(agendamento.fim)
                inicio_minutos = max(
                    minutos_inicio,
                    inicio_local.hour * 60 + inicio_local.minute,
                )
                fim_minutos = min(
                    minutos_fim,
                    fim_local.hour * 60 + fim_local.minute,
                )
                cards.append(
                    {
                        "agendamento": agendamento,
                        "top": round((inicio_minutos - minutos_inicio) * escala_minuto),
                        "altura": max(28, round((fim_minutos - inicio_minutos) * escala_minuto)),
                    }
                )
            colunas.append({"profissional": profissional, "cards": cards})

        contexto.update(
            {
                "colunas": colunas,
                "largura_minima_agenda": max(760, 72 + len(colunas) * 220),
                "altura_grade": round((minutos_fim - minutos_inicio) * escala_minuto),
                "marcadores_hora": [
                    {
                        "rotulo": f"{minuto // 60:02d}:00",
                        "top": round((minuto - minutos_inicio) * escala_minuto),
                    }
                    for minuto in range(minutos_inicio, minutos_fim + 1, 60)
                ],
                "passo_hora": round(60 * escala_minuto),
            }
        )
    else:
        agendamentos_por_dia = {}
        for agendamento in agendamentos:
            dia = timezone.localtime(agendamento.inicio).date()
            agendamentos_por_dia.setdefault(dia, []).append(agendamento)
        contexto["dias_semana"] = [
            {
                "data": inicio_periodo_data + timedelta(days=indice),
                "nome": NOMES_DIAS_SEMANA[indice],
                "hoje": inicio_periodo_data + timedelta(days=indice)
                == timezone.localdate(),
                "agendamentos": agendamentos_por_dia.get(
                    inicio_periodo_data + timedelta(days=indice),
                    [],
                ),
            }
            for indice in range(7)
        ]
        contexto["inicio_semana"] = inicio_periodo_data
        contexto["fim_semana"] = fim_periodo_data - timedelta(days=1)

    return render(request, "gestao/agenda_visual.html", contexto)


class ClienteListaView(QuerysetDaBarbeariaMixin, ListView):
    model = Cliente
    template_name = "gestao/cliente_lista.html"
    context_object_name = "clientes"
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset()
        termo = self.request.GET.get("q", "").strip()
        if termo:
            queryset = queryset.filter(nome__icontains=termo)
        return queryset


class ClienteCriarView(
    GestorObrigatorioMixin,
    FormDaBarbeariaMixin,
    CreateView,
):
    model = Cliente
    form_class = ClienteForm
    template_name = "gestao/formulario.html"
    extra_context = {"titulo": "Novo cliente", "voltar_url": "cliente_lista"}

    def form_valid(self, form):
        messages.success(self.request, "Cliente cadastrado com sucesso.")
        return super().form_valid(form)


class ClienteEditarView(
    GestorObrigatorioMixin,
    FormDaBarbeariaMixin,
    QuerysetDaBarbeariaMixin,
    UpdateView,
):
    model = Cliente
    form_class = ClienteForm
    template_name = "gestao/formulario.html"
    extra_context = {"titulo": "Editar cliente", "voltar_url": "cliente_lista"}

    def form_valid(self, form):
        messages.success(self.request, "Cliente atualizado com sucesso.")
        return super().form_valid(form)


class ServicoListaView(QuerysetDaBarbeariaMixin, ListView):
    model = Servico
    template_name = "gestao/servico_lista.html"
    context_object_name = "servicos"


class ServicoCriarView(
    GestorObrigatorioMixin,
    FormDaBarbeariaMixin,
    CreateView,
):
    model = Servico
    form_class = ServicoForm
    template_name = "gestao/formulario.html"
    extra_context = {"titulo": "Novo serviço", "voltar_url": "servico_lista"}

    def form_valid(self, form):
        messages.success(self.request, "Serviço cadastrado com sucesso.")
        return super().form_valid(form)


class ServicoEditarView(
    GestorObrigatorioMixin,
    FormDaBarbeariaMixin,
    QuerysetDaBarbeariaMixin,
    UpdateView,
):
    model = Servico
    form_class = ServicoForm
    template_name = "gestao/formulario.html"
    extra_context = {"titulo": "Editar serviço", "voltar_url": "servico_lista"}

    def form_valid(self, form):
        messages.success(self.request, "Serviço atualizado com sucesso.")
        return super().form_valid(form)


class AgendamentoListaView(QuerysetDaBarbeariaMixin, ListView):
    model = Agendamento
    template_name = "gestao/agendamento_lista.html"
    context_object_name = "agendamentos"
    paginate_by = 30

    def get_queryset(self):
        return super().get_queryset().select_related(
            "cliente", "profissional", "servico"
        )


class AgendamentoCriarView(
    GestorObrigatorioMixin,
    FormDaBarbeariaMixin,
    CreateView,
):
    model = Agendamento
    form_class = AgendamentoForm
    template_name = "gestao/formulario.html"
    extra_context = {
        "titulo": "Novo agendamento",
        "voltar_url": "agendamento_lista",
    }

    def form_valid(self, form):
        messages.success(self.request, "Agendamento criado com sucesso.")
        response = super().form_valid(form)
        sincronizar_notificacoes(self.object, incluir_confirmacao=True)
        return response


class AgendamentoEditarView(
    GestorObrigatorioMixin,
    FormDaBarbeariaMixin,
    QuerysetDaBarbeariaMixin,
    UpdateView,
):
    model = Agendamento
    form_class = AgendamentoForm
    template_name = "gestao/formulario.html"
    extra_context = {
        "titulo": "Editar agendamento",
        "voltar_url": "agendamento_lista",
    }

    def form_valid(self, form):
        messages.success(self.request, "Agendamento atualizado com sucesso.")
        response = super().form_valid(form)
        sincronizar_notificacoes(self.object)
        return response


@login_required
def cancelar_agendamento(request, pk):
    if request.method != "POST":
        return redirect("agendamento_lista")
    if not request.user.pode_gerenciar:
        raise PermissionDenied

    agendamento = get_object_or_404(
        Agendamento,
        pk=pk,
        barbearia=request.user.barbearia,
    )
    Agendamento.objects.filter(pk=agendamento.pk).update(
        status=Agendamento.Status.CANCELADO,
        atualizado_em=timezone.now(),
    )
    cancelar_notificacoes(agendamento)
    messages.success(request, "Agendamento cancelado.")
    return redirect("agendamento_lista")


@require_http_methods(["GET", "POST"])
def agendamento_publico(request, slug):
    barbearia = get_object_or_404(Barbearia, slug=slug, ativa=True)
    if request.method == "POST" and _limite_publico_excedido(request, "agendar", 8, 600):
        return render(
            request,
            "gestao/agendamento_publico_limite.html",
            {"barbearia": barbearia},
            status=429,
        )
    form = AgendamentoPublicoForm(
        request.POST or None,
        barbearia=barbearia,
    )

    if request.method == "POST" and "consultar_horarios" not in request.POST and form.is_valid():
        try:
            with transaction.atomic():
                profissional = Usuario.objects.select_for_update().get(
                    pk=form.cleaned_data["profissional"].pk,
                    barbearia=barbearia,
                    papel=Usuario.Papel.BARBEIRO,
                    is_active=True,
                )
                opcoes_atuais = horarios_disponiveis(
                    barbearia,
                    profissional,
                    form.cleaned_data["servico"],
                    form.cleaned_data["data"],
                )
                if form.inicio not in opcoes_atuais:
                    raise ValidationError("O horário acabou de ser ocupado.")

                cliente = Cliente.objects.filter(
                    barbearia=barbearia,
                    telefone=form.cleaned_data["telefone"],
                ).first()
                if cliente is None:
                    cliente = Cliente.objects.create(
                        barbearia=barbearia,
                        nome=form.cleaned_data["nome"],
                        telefone=form.cleaned_data["telefone"],
                        email=form.cleaned_data["email"],
                        aceita_notificacoes_whatsapp=form.cleaned_data[
                            "aceita_notificacoes_whatsapp"
                        ],
                    )
                else:
                    campos_cliente = []
                    if cliente.nome != form.cleaned_data["nome"]:
                        cliente.nome = form.cleaned_data["nome"]
                        campos_cliente.append("nome")
                    if cliente.email != form.cleaned_data["email"]:
                        cliente.email = form.cleaned_data["email"]
                        campos_cliente.append("email")
                    if not cliente.ativo:
                        cliente.ativo = True
                        campos_cliente.append("ativo")
                    consentimento = form.cleaned_data[
                        "aceita_notificacoes_whatsapp"
                    ]
                    if cliente.aceita_notificacoes_whatsapp != consentimento:
                        cliente.aceita_notificacoes_whatsapp = consentimento
                        campos_cliente.append("aceita_notificacoes_whatsapp")
                    if campos_cliente:
                        cliente.save(
                            update_fields=[*campos_cliente, "atualizado_em"]
                        )

                agendamento = Agendamento.objects.create(
                    barbearia=barbearia,
                    cliente=cliente,
                    profissional=profissional,
                    servico=form.cleaned_data["servico"],
                    inicio=form.inicio,
                    status=Agendamento.Status.AGENDADO,
                    origem=Agendamento.Origem.ONLINE,
                    observacoes="Agendado pelo cliente no link público.",
                )
                sincronizar_notificacoes(agendamento, incluir_confirmacao=True)
        except (ValidationError, Usuario.DoesNotExist):
            form.add_error(
                "horario",
                "Esse horário não está mais disponível. Atualize as opções e escolha outro.",
            )
        else:
            request.session["ultimo_agendamento_publico"] = agendamento.pk
            return redirect("agendamento_publico_confirmacao", slug=barbearia.slug)

    return render(
        request,
        "gestao/agendamento_publico.html",
        {
            "barbearia": barbearia,
            "form": form,
            "servicos": form.fields["servico"].queryset,
            "profissionais": form.fields["profissional"].queryset,
            "telefone_href": _telefone_href(barbearia.telefone),
        },
    )


@require_GET
def horarios_disponiveis_publico(request, slug):
    barbearia = get_object_or_404(Barbearia, slug=slug, ativa=True)
    if _limite_publico_excedido(request, "horarios", 120, 60):
        return JsonResponse({"erro": "Muitas consultas. Aguarde um instante."}, status=429)
    try:
        data = date.fromisoformat(request.GET.get("data", ""))
    except ValueError:
        return JsonResponse({"horarios": []})

    profissional = get_object_or_404(
        Usuario,
        pk=request.GET.get("profissional"),
        barbearia=barbearia,
        papel=Usuario.Papel.BARBEIRO,
        is_active=True,
    )
    servico = get_object_or_404(
        Servico,
        pk=request.GET.get("servico"),
        barbearia=barbearia,
        ativo=True,
    )
    opcoes = horarios_disponiveis(barbearia, profissional, servico, data)
    return JsonResponse(
        {
            "horarios": [
                {"valor": opcao.strftime("%H:%M"), "texto": opcao.strftime("%H:%M")}
                for opcao in opcoes
            ]
        }
    )


@require_GET
def agendamento_publico_confirmacao(request, slug):
    barbearia = get_object_or_404(Barbearia, slug=slug, ativa=True)
    agendamento_id = request.session.get("ultimo_agendamento_publico")
    agendamento = get_object_or_404(
        Agendamento.objects.select_related("cliente", "profissional", "servico"),
        pk=agendamento_id,
        barbearia=barbearia,
        origem=Agendamento.Origem.ONLINE,
    )
    return render(
        request,
        "gestao/agendamento_publico_confirmacao.html",
        {"barbearia": barbearia, "agendamento": agendamento},
    )


def _obter_agendamento_publico(slug, token, bloquear=False):
    queryset = Agendamento.objects.select_related("barbearia", "cliente", "profissional", "servico")
    if bloquear:
        queryset = queryset.select_for_update()
    return get_object_or_404(
        queryset,
        barbearia__slug=slug,
        barbearia__ativa=True,
        token_publico=token,
        origem=Agendamento.Origem.ONLINE,
    )


@require_GET
def agendamento_publico_gerenciar(request, slug, token):
    agendamento = _obter_agendamento_publico(slug, token)
    limite = agendamento.inicio - timedelta(
        hours=agendamento.barbearia.antecedencia_cancelamento_horas
    )
    pode_alterar = (
        agendamento.status in {Agendamento.Status.AGENDADO, Agendamento.Status.CONFIRMADO}
        and timezone.now() < limite
    )
    return render(
        request,
        "gestao/agendamento_publico_gerenciar.html",
        {"barbearia": agendamento.barbearia, "agendamento": agendamento, "pode_alterar": pode_alterar},
    )


@require_POST
def agendamento_publico_cancelar(request, slug, token):
    if _limite_publico_excedido(request, "cancelar", 8, 600):
        return HttpResponse("Muitas tentativas. Aguarde alguns minutos.", status=429)
    with transaction.atomic():
        agendamento = _obter_agendamento_publico(slug, token, bloquear=True)
        limite = agendamento.inicio - timedelta(
            hours=agendamento.barbearia.antecedencia_cancelamento_horas
        )
        if agendamento.status not in {Agendamento.Status.AGENDADO, Agendamento.Status.CONFIRMADO}:
            messages.error(request, "Este agendamento não pode mais ser cancelado.")
        elif timezone.now() >= limite:
            messages.error(request, "O prazo para cancelamento on-line foi encerrado. Entre em contato com a barbearia.")
        else:
            agendamento.status = Agendamento.Status.CANCELADO
            agendamento.save(update_fields=["status", "atualizado_em"])
            cancelar_notificacoes(agendamento)
            messages.success(request, "Agendamento cancelado com sucesso.")
    return redirect("agendamento_publico_gerenciar", slug=slug, token=token)


@require_http_methods(["GET", "POST"])
def agendamento_publico_reagendar(request, slug, token):
    agendamento = _obter_agendamento_publico(slug, token)
    limite = agendamento.inicio - timedelta(
        hours=agendamento.barbearia.antecedencia_cancelamento_horas
    )
    if agendamento.status not in {Agendamento.Status.AGENDADO, Agendamento.Status.CONFIRMADO} or timezone.now() >= limite:
        messages.error(request, "Este agendamento não está disponível para reagendamento on-line.")
        return redirect("agendamento_publico_gerenciar", slug=slug, token=token)
    if request.method == "POST" and _limite_publico_excedido(request, "reagendar", 8, 600):
        return HttpResponse("Muitas tentativas. Aguarde alguns minutos.", status=429)

    form = ReagendamentoPublicoForm(
        request.POST or None,
        agendamento=agendamento,
        initial={
            "servico": agendamento.servico_id,
            "profissional": agendamento.profissional_id,
            "data": timezone.localtime(agendamento.inicio).date(),
            "horario": timezone.localtime(agendamento.inicio).strftime("%H:%M"),
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                agendamento = _obter_agendamento_publico(slug, token, bloquear=True)
                profissional = Usuario.objects.select_for_update().get(
                    pk=form.cleaned_data["profissional"].pk,
                    barbearia=agendamento.barbearia,
                    papel=Usuario.Papel.BARBEIRO,
                    is_active=True,
                )
                opcoes = horarios_disponiveis(
                    agendamento.barbearia, profissional, form.cleaned_data["servico"],
                    form.cleaned_data["data"], agendamento,
                )
                if form.inicio not in opcoes:
                    raise ValidationError("Horário indisponível")
                agendamento.profissional = profissional
                agendamento.servico = form.cleaned_data["servico"]
                agendamento.inicio = form.inicio
                agendamento.preco_cobrado = form.cleaned_data["servico"].preco
                agendamento.status = Agendamento.Status.AGENDADO
                agendamento.save()
                sincronizar_notificacoes(agendamento, incluir_confirmacao=True)
        except (ValidationError, Usuario.DoesNotExist):
            form.add_error("horario", "Esse horário não está mais disponível.")
        else:
            messages.success(request, "Agendamento atualizado com sucesso.")
            return redirect("agendamento_publico_gerenciar", slug=slug, token=token)
    return render(
        request,
        "gestao/agendamento_publico_reagendar.html",
        {"barbearia": agendamento.barbearia, "agendamento": agendamento, "form": form},
    )


@require_GET
def politica_privacidade_publica(request, slug):
    barbearia = get_object_or_404(Barbearia, slug=slug, ativa=True)
    return render(request, "gestao/politica_privacidade_publica.html", {"barbearia": barbearia})


@login_required
@require_http_methods(["GET", "POST"])
def configuracao_publica(request):
    _exigir_proprietario(request)
    form = ConfiguracaoPublicaForm(request.POST or None, instance=request.user.barbearia)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Página pública atualizada com sucesso.")
        return redirect("configuracao_publica")
    return render(request, "gestao/configuracao_publica.html", {"form": form})
