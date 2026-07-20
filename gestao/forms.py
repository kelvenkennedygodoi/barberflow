from datetime import timedelta
from decimal import Decimal

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    Agendamento,
    Barbearia,
    BloqueioAgenda,
    Cliente,
    HorarioTrabalho,
    Servico,
    Usuario,
    normalizar_telefone,
)
from .services import horarios_disponiveis


class FormBase:
    def aplicar_estilos(self):
        for campo in self.fields.values():
            if isinstance(campo.widget, forms.CheckboxInput):
                campo.widget.attrs["class"] = "form-check"
            else:
                campo.widget.attrs["class"] = "form-control"


class ClienteForm(FormBase, forms.ModelForm):
    class Meta:
        model = Cliente
        fields = [
            "nome",
            "telefone",
            "email",
            "observacoes",
            "aceita_notificacoes_whatsapp",
            "ativo",
        ]
        labels = {
            "aceita_notificacoes_whatsapp": "Autoriza confirmações e lembretes pelo WhatsApp",
        }
        widgets = {"observacoes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilos()


class ServicoForm(FormBase, forms.ModelForm):
    class Meta:
        model = Servico
        fields = ["nome", "descricao", "duracao_minutos", "preco", "ativo"]
        labels = {
            "duracao_minutos": "Duração em minutos",
            "preco": "Preço (R$)",
        }
        widgets = {"descricao": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilos()


class AgendamentoForm(FormBase, forms.ModelForm):
    class Meta:
        model = Agendamento
        fields = [
            "cliente",
            "profissional",
            "servico",
            "inicio",
            "status",
            "preco_cobrado",
            "observacoes",
        ]
        labels = {
            "inicio": "Data e horário",
            "preco_cobrado": "Preço cobrado (R$)",
        }
        help_texts = {
            "preco_cobrado": "Deixe vazio para usar o preço atual do serviço."
        }
        widgets = {
            "inicio": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, barbearia=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["inicio"].input_formats = ["%Y-%m-%dT%H:%M"]
        if barbearia:
            self.fields["cliente"].queryset = Cliente.objects.filter(
                barbearia=barbearia,
                ativo=True,
            )
            self.fields["profissional"].queryset = Usuario.objects.filter(
                barbearia=barbearia,
                papel=Usuario.Papel.BARBEIRO,
                is_active=True,
            )
            self.fields["servico"].queryset = Servico.objects.filter(
                barbearia=barbearia,
                ativo=True,
            )
        else:
            self.fields["cliente"].queryset = Cliente.objects.none()
            self.fields["profissional"].queryset = Usuario.objects.none()
            self.fields["servico"].queryset = Servico.objects.none()
        self.aplicar_estilos()


class ProfissionalChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.nome_exibicao


class ServicoChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.nome} — {obj.duracao_minutos} min — R$ {obj.preco:.2f}"


class AgendamentoPublicoForm(FormBase, forms.Form):
    nome = forms.CharField(label="Seu nome", max_length=120)
    telefone = forms.CharField(
        label="WhatsApp ou telefone",
        max_length=20,
        widget=forms.TextInput(attrs={"type": "tel", "placeholder": "(32) 99999-9999"}),
    )
    email = forms.EmailField(label="E-mail", required=False)
    servico = ServicoChoiceField(
        queryset=Servico.objects.none(),
        empty_label=None,
        label="Serviço",
        widget=forms.RadioSelect,
    )
    profissional = ProfissionalChoiceField(
        queryset=Usuario.objects.none(),
        empty_label=None,
        label="Barbeiro",
        widget=forms.RadioSelect,
    )
    data = forms.DateField(
        label="Data",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    horario = forms.ChoiceField(
        label="Horário disponível",
        choices=[("", "Escolha serviço, barbeiro e data")],
        error_messages={
            "invalid_choice": "Esse horário não está mais disponível. Escolha outro."
        },
    )
    confirmacao_dados = forms.BooleanField(
        label="Confirmo que os dados serão usados para organizar este atendimento.",
    )
    aceita_notificacoes_whatsapp = forms.BooleanField(
        label="Quero receber a confirmação e os lembretes deste horário pelo WhatsApp.",
        required=False,
        initial=False,
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, barbearia, agendamento_ignorado=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.barbearia = barbearia
        self.agendamento_ignorado = agendamento_ignorado
        self.inicio = None
        self.fields["servico"].queryset = Servico.objects.filter(
            barbearia=barbearia,
            ativo=True,
        )
        self.fields["profissional"].queryset = Usuario.objects.filter(
            barbearia=barbearia,
            papel=Usuario.Papel.BARBEIRO,
            is_active=True,
        )

        hoje = timezone.localdate()
        self.fields["data"].widget.attrs.update(
            {
                "min": hoje.isoformat(),
                "max": (hoje + timedelta(days=barbearia.limite_agendamento_dias)).isoformat(),
            }
        )
        self._carregar_horarios_do_formulario()
        self.aplicar_estilos()

    def _carregar_horarios_do_formulario(self):
        if not self.is_bound:
            return
        try:
            servico = self.fields["servico"].queryset.get(pk=self.data.get("servico"))
            profissional = self.fields["profissional"].queryset.get(
                pk=self.data.get("profissional")
            )
            data = forms.DateField().to_python(self.data.get("data"))
        except (Servico.DoesNotExist, Usuario.DoesNotExist, ValidationError, ValueError, TypeError):
            return
        if not data:
            return
        opcoes = [
            (inicio.strftime("%H:%M"), inicio.strftime("%H:%M"))
            for inicio in horarios_disponiveis(
                self.barbearia,
                profissional,
                servico,
                data,
                self.agendamento_ignorado,
            )
        ]
        self.fields["horario"].choices = [
            ("", "Selecione um horário" if opcoes else "Nenhum horário disponível"),
            *opcoes,
        ]

    def clean_telefone(self):
        telefone = normalizar_telefone(self.cleaned_data["telefone"])
        if len(telefone) < 10:
            raise forms.ValidationError("Informe um telefone com DDD.")
        return telefone

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Não foi possível enviar o formulário.")
        return ""

    def clean(self):
        cleaned_data = super().clean()
        servico = cleaned_data.get("servico")
        profissional = cleaned_data.get("profissional")
        data = cleaned_data.get("data")
        horario = cleaned_data.get("horario")
        if not all([servico, profissional, data, horario]):
            return cleaned_data

        opcoes = horarios_disponiveis(
            self.barbearia,
            profissional,
            servico,
            data,
            self.agendamento_ignorado,
        )
        self.inicio = next(
            (opcao for opcao in opcoes if opcao.strftime("%H:%M") == horario),
            None,
        )
        if self.inicio is None:
            self.add_error(
                "horario",
                "Esse horário não está mais disponível. Escolha outro.",
            )
        return cleaned_data


class ReagendamentoPublicoForm(AgendamentoPublicoForm):
    """Reutiliza as mesmas regras sem pedir novamente os dados do cliente."""

    def __init__(self, *args, agendamento, **kwargs):
        self.agendamento = agendamento
        kwargs.setdefault("barbearia", agendamento.barbearia)
        kwargs.setdefault("agendamento_ignorado", agendamento)
        super().__init__(*args, **kwargs)
        for nome in (
            "nome", "telefone", "email", "confirmacao_dados",
            "aceita_notificacoes_whatsapp", "website",
        ):
            self.fields.pop(nome)
        if not self.is_bound:
            data = timezone.localtime(agendamento.inicio).date()
            opcoes = horarios_disponiveis(
                agendamento.barbearia,
                agendamento.profissional,
                agendamento.servico,
                data,
                agendamento,
            )
            self.fields["horario"].choices = [
                ("", "Selecione um horário"),
                *((inicio.strftime("%H:%M"), inicio.strftime("%H:%M")) for inicio in opcoes),
            ]


class ConfiguracaoPublicaForm(FormBase, forms.ModelForm):
    class Meta:
        model = Barbearia
        fields = (
            "nome", "telefone", "email", "endereco", "descricao_publica",
            "logo_url", "mapa_url", "instagram", "horario_funcionamento",
            "politica_cancelamento", "politica_privacidade",
            "antecedencia_agendamento_minutos", "limite_agendamento_dias",
            "intervalo_agendamento_minutos", "antecedencia_cancelamento_horas",
        )
        labels = {
            "descricao_publica": "Apresentação da barbearia",
            "logo_url": "URL da logomarca",
            "mapa_url": "Link do mapa",
            "horario_funcionamento": "Horário de funcionamento",
            "politica_cancelamento": "Política de cancelamento e atrasos",
            "politica_privacidade": "Política de privacidade",
            "antecedencia_agendamento_minutos": "Antecedência mínima para agendar (minutos)",
            "limite_agendamento_dias": "Quantos dias à frente podem ser agendados",
            "intervalo_agendamento_minutos": "Intervalo entre opções de horário (minutos)",
            "antecedencia_cancelamento_horas": "Antecedência mínima para cancelar (horas)",
        }
        widgets = {
            "descricao_publica": forms.Textarea(attrs={"rows": 3}),
            "horario_funcionamento": forms.Textarea(attrs={"rows": 3}),
            "politica_cancelamento": forms.Textarea(attrs={"rows": 4}),
            "politica_privacidade": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilos()

    def clean_intervalo_agendamento_minutos(self):
        valor = self.cleaned_data["intervalo_agendamento_minutos"]
        if valor not in {5, 10, 15, 20, 30, 60}:
            raise forms.ValidationError("Use 5, 10, 15, 20, 30 ou 60 minutos.")
        return valor


class HorarioTrabalhoForm(FormBase, forms.ModelForm):
    class Meta:
        model = HorarioTrabalho
        fields = ["dia_semana", "inicio", "fim", "ativo"]
        labels = {
            "dia_semana": "Dia da semana",
            "inicio": "Horário inicial",
            "fim": "Horário final",
        }
        widgets = {
            "inicio": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "fim": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["inicio"].input_formats = ["%H:%M"]
        self.fields["fim"].input_formats = ["%H:%M"]
        self.aplicar_estilos()


class BloqueioAgendaForm(FormBase, forms.ModelForm):
    class Meta:
        model = BloqueioAgenda
        fields = ["inicio", "fim", "motivo"]
        labels = {
            "inicio": "Início da indisponibilidade",
            "fim": "Fim da indisponibilidade",
            "motivo": "Motivo",
        }
        widgets = {
            "inicio": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "fim": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "motivo": forms.TextInput(
                attrs={"placeholder": "Ex.: folga, consulta ou férias"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["inicio"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["fim"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.aplicar_estilos()


class FuncionarioFormMixin:
    papeis_funcionario = (
        (Usuario.Papel.BARBEIRO, "Barbeiro"),
        (Usuario.Papel.RECEPCIONISTA, "Recepcionista"),
    )

    def configurar_campos_funcionario(self):
        self.fields["first_name"].required = True
        self.fields["papel"].choices = self.papeis_funcionario
        self.fields["username"].label = "Usuário de acesso"
        self.fields["first_name"].label = "Nome"
        self.fields["last_name"].label = "Sobrenome"
        self.fields["email"].label = "E-mail"
        self.fields["telefone"].label = "Telefone"
        self.fields["especialidades"].label = "Especialidades exibidas ao cliente"
        self.fields["foto_url"].label = "URL da foto profissional"
        self.fields["papel"].label = "Função"
        self.fields["comissao_percentual"].label = "Comissão (%)"
        self.aplicar_estilos()

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        conflito = Usuario.objects.filter(username__iexact=username).exclude(
            pk=self.instance.pk
        )
        if conflito.exists():
            raise forms.ValidationError("Este usuário de acesso já está em uso.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if email and self.instance.barbearia_id:
            conflito = Usuario.objects.filter(
                barbearia_id=self.instance.barbearia_id,
                email__iexact=email,
            ).exclude(pk=self.instance.pk)
            if conflito.exists():
                raise forms.ValidationError("Este e-mail já pertence a outro funcionário.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("papel") == Usuario.Papel.RECEPCIONISTA:
            cleaned_data["comissao_percentual"] = Decimal("0.00")
        return cleaned_data


class FuncionarioCriacaoForm(
    FuncionarioFormMixin,
    FormBase,
    UserCreationForm,
):
    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "telefone",
            "especialidades",
            "foto_url",
            "papel",
            "comissao_percentual",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Senha"
        self.fields["password2"].label = "Confirmar senha"
        self.order_fields(
            [
                "first_name",
                "last_name",
                "username",
                "email",
                "telefone",
                "especialidades",
                "foto_url",
                "papel",
                "comissao_percentual",
                "password1",
                "password2",
            ]
        )
        self.configurar_campos_funcionario()


class FuncionarioEdicaoForm(
    FuncionarioFormMixin,
    FormBase,
    forms.ModelForm,
):
    nova_senha1 = forms.CharField(
        label="Nova senha",
        required=False,
        widget=forms.PasswordInput,
        help_text="Deixe vazio para manter a senha atual.",
    )
    nova_senha2 = forms.CharField(
        label="Confirmar nova senha",
        required=False,
        widget=forms.PasswordInput,
    )

    class Meta:
        model = Usuario
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "telefone",
            "especialidades",
            "foto_url",
            "papel",
            "comissao_percentual",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.configurar_campos_funcionario()

    def clean(self):
        cleaned_data = super().clean()
        senha1 = cleaned_data.get("nova_senha1")
        senha2 = cleaned_data.get("nova_senha2")
        if senha1 or senha2:
            if senha1 != senha2:
                self.add_error("nova_senha2", "As senhas não coincidem.")
            else:
                try:
                    validate_password(senha1, self.instance)
                except ValidationError as exc:
                    self.add_error("nova_senha1", exc)

        novo_papel = cleaned_data.get("papel")
        if (
            self.instance.pk
            and self.instance.papel == Usuario.Papel.BARBEIRO
            and novo_papel != Usuario.Papel.BARBEIRO
            and (
                self.instance.agendamentos.exists()
                or self.instance.horarios_trabalho.exists()
                or self.instance.bloqueios_agenda.exists()
            )
        ):
            self.add_error(
                "papel",
                "Este barbeiro possui agenda ou histórico. Desative o acesso em vez de alterar a função.",
            )
        return cleaned_data

    def save(self, commit=True):
        funcionario = super().save(commit=False)
        nova_senha = self.cleaned_data.get("nova_senha1")
        if nova_senha:
            funcionario.set_password(nova_senha)
        if commit:
            funcionario.save()
            self.save_m2m()
        return funcionario


class ConclusaoAtendimentoForm(FormBase, forms.Form):
    preco_cobrado = forms.DecimalField(
        label="Valor final (R$)",
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.00"),
    )
    forma_pagamento = forms.ChoiceField(
        label="Forma de pagamento",
        choices=[("", "Selecione a forma de pagamento"), *Agendamento.FormaPagamento.choices],
    )

    def __init__(self, *args, agendamento=None, **kwargs):
        if agendamento and "initial" not in kwargs:
            kwargs["initial"] = {"preco_cobrado": agendamento.preco_cobrado}
        super().__init__(*args, **kwargs)
        self.agendamento = agendamento
        self.aplicar_estilos()


class FinanceiroFiltroForm(FormBase, forms.Form):
    PAGAMENTO_NAO_INFORMADO = "NAO_INFORMADO"

    data_inicio = forms.DateField(
        label="De",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    data_fim = forms.DateField(
        label="Até",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    profissional = ProfissionalChoiceField(
        label="Barbeiro",
        queryset=Usuario.objects.none(),
        required=False,
        empty_label="Todos os barbeiros",
    )
    forma_pagamento = forms.ChoiceField(
        label="Pagamento",
        required=False,
        choices=[
            ("", "Todas as formas"),
            *Agendamento.FormaPagamento.choices,
            (PAGAMENTO_NAO_INFORMADO, "Não informado"),
        ],
    )

    def __init__(self, *args, barbearia=None, **kwargs):
        super().__init__(*args, **kwargs)
        if barbearia:
            self.fields["profissional"].queryset = Usuario.objects.filter(
                barbearia=barbearia,
                papel=Usuario.Papel.BARBEIRO,
            ).order_by("first_name", "username")
        self.aplicar_estilos()

    def clean(self):
        cleaned_data = super().clean()
        data_inicio = cleaned_data.get("data_inicio")
        data_fim = cleaned_data.get("data_fim")
        if data_inicio and data_fim:
            if data_fim < data_inicio:
                self.add_error(
                    "data_fim",
                    "A data final deve ser igual ou posterior à data inicial.",
                )
            elif (data_fim - data_inicio).days > 365:
                self.add_error(
                    "data_fim",
                    "Selecione um período de no máximo 366 dias.",
                )
        return cleaned_data
