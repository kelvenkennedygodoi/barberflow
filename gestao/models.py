from datetime import timedelta
import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone


def normalizar_telefone(valor):
    return "".join(caractere for caractere in (valor or "") if caractere.isdigit())


class Barbearia(models.Model):
    nome = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    telefone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    endereco = models.CharField(max_length=255, blank=True)
    descricao_publica = models.TextField(blank=True)
    logo_url = models.URLField(blank=True)
    mapa_url = models.URLField(blank=True)
    instagram = models.CharField(max_length=80, blank=True)
    horario_funcionamento = models.TextField(blank=True)
    politica_cancelamento = models.TextField(blank=True)
    politica_privacidade = models.TextField(blank=True)
    antecedencia_agendamento_minutos = models.PositiveSmallIntegerField(default=30)
    limite_agendamento_dias = models.PositiveSmallIntegerField(default=60)
    intervalo_agendamento_minutos = models.PositiveSmallIntegerField(default=15)
    antecedencia_cancelamento_horas = models.PositiveSmallIntegerField(default=2)
    ativa = models.BooleanField(default=True)
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "barbearia"
        verbose_name_plural = "barbearias"

    def __str__(self):
        return self.nome


class Usuario(AbstractUser):
    class Papel(models.TextChoices):
        PROPRIETARIO = "PROPRIETARIO", "Proprietário"
        RECEPCIONISTA = "RECEPCIONISTA", "Recepcionista"
        BARBEIRO = "BARBEIRO", "Barbeiro"

    barbearia = models.ForeignKey(
        Barbearia,
        on_delete=models.PROTECT,
        related_name="usuarios",
        null=True,
        blank=True,
    )
    papel = models.CharField(
        max_length=20,
        choices=Papel.choices,
        default=Papel.BARBEIRO,
    )
    telefone = models.CharField(max_length=20, blank=True)
    especialidades = models.CharField(max_length=180, blank=True)
    foto_url = models.URLField(blank=True)
    comissao_percentual = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    @property
    def nome_exibicao(self):
        return self.get_full_name() or self.username

    @property
    def pode_gerenciar(self):
        return self.is_superuser or self.papel in {
            self.Papel.PROPRIETARIO,
            self.Papel.RECEPCIONISTA,
        }

    def clean(self):
        super().clean()
        if not self.is_superuser and not self.barbearia_id:
            raise ValidationError({"barbearia": "Informe a barbearia deste usuário."})


class Cliente(models.Model):
    barbearia = models.ForeignKey(
        Barbearia,
        on_delete=models.CASCADE,
        related_name="clientes",
    )
    nome = models.CharField(max_length=120)
    telefone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    observacoes = models.TextField(blank=True)
    aceita_notificacoes_whatsapp = models.BooleanField(
        default=False,
        verbose_name="Aceita notificações pelo WhatsApp",
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        constraints = [
            models.UniqueConstraint(
                fields=["barbearia", "telefone"],
                condition=~Q(telefone=""),
                name="cliente_telefone_unico_por_barbearia",
            )
        ]
        indexes = [models.Index(fields=["barbearia", "nome"])]

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        self.telefone = normalizar_telefone(self.telefone)
        return super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("cliente_lista")


class Servico(models.Model):
    barbearia = models.ForeignKey(
        Barbearia,
        on_delete=models.CASCADE,
        related_name="servicos",
    )
    nome = models.CharField(max_length=100)
    descricao = models.TextField(blank=True)
    duracao_minutos = models.PositiveSmallIntegerField(
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(480)],
    )
    preco = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "serviço"
        verbose_name_plural = "serviços"
        constraints = [
            models.UniqueConstraint(
                fields=["barbearia", "nome"],
                name="servico_nome_unico_por_barbearia",
            )
        ]

    def __str__(self):
        return f"{self.nome} ({self.duracao_minutos} min)"

    def get_absolute_url(self):
        return reverse("servico_lista")


class HorarioTrabalho(models.Model):
    class DiaSemana(models.IntegerChoices):
        SEGUNDA = 0, "Segunda-feira"
        TERCA = 1, "Terça-feira"
        QUARTA = 2, "Quarta-feira"
        QUINTA = 3, "Quinta-feira"
        SEXTA = 4, "Sexta-feira"
        SABADO = 5, "Sábado"
        DOMINGO = 6, "Domingo"

    barbearia = models.ForeignKey(
        Barbearia,
        on_delete=models.CASCADE,
        related_name="horarios_trabalho",
    )
    profissional = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name="horarios_trabalho",
        limit_choices_to={"papel": Usuario.Papel.BARBEIRO},
    )
    dia_semana = models.PositiveSmallIntegerField(choices=DiaSemana.choices)
    inicio = models.TimeField()
    fim = models.TimeField()
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["profissional", "dia_semana", "inicio"]
        verbose_name = "horário de trabalho"
        verbose_name_plural = "horários de trabalho"
        constraints = [
            models.CheckConstraint(
                condition=Q(fim__gt=models.F("inicio")),
                name="horario_trabalho_fim_apos_inicio",
            ),
            models.UniqueConstraint(
                fields=["profissional", "dia_semana", "inicio", "fim"],
                name="horario_trabalho_sem_duplicidade",
            ),
        ]

    def __str__(self):
        return (
            f"{self.profissional.nome_exibicao} — {self.get_dia_semana_display()} "
            f"{self.inicio:%H:%M}–{self.fim:%H:%M}"
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.profissional_id and self.barbearia_id:
            if self.profissional.barbearia_id != self.barbearia_id:
                errors["profissional"] = "O profissional pertence a outra barbearia."
            if self.profissional.papel != Usuario.Papel.BARBEIRO:
                errors["profissional"] = "Selecione um usuário com papel de barbeiro."
        if self.inicio and self.fim and self.fim <= self.inicio:
            errors["fim"] = "O horário final deve ser posterior ao inicial."
        if errors:
            raise ValidationError(errors)

        if (
            self.ativo
            and self.profissional_id
            and self.dia_semana is not None
            and self.inicio
            and self.fim
        ):
            conflito = (
                HorarioTrabalho.objects.filter(
                    profissional_id=self.profissional_id,
                    dia_semana=self.dia_semana,
                    ativo=True,
                    inicio__lt=self.fim,
                    fim__gt=self.inicio,
                )
                .exclude(pk=self.pk)
                .exists()
            )
            if conflito:
                raise ValidationError(
                    {"inicio": "Este período se sobrepõe a outro horário de trabalho."}
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class BloqueioAgenda(models.Model):
    barbearia = models.ForeignKey(
        Barbearia,
        on_delete=models.CASCADE,
        related_name="bloqueios_agenda",
    )
    profissional = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name="bloqueios_agenda",
        limit_choices_to={"papel": Usuario.Papel.BARBEIRO},
    )
    inicio = models.DateTimeField()
    fim = models.DateTimeField()
    motivo = models.CharField(max_length=160, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["inicio"]
        verbose_name = "bloqueio de agenda"
        verbose_name_plural = "bloqueios de agenda"
        constraints = [
            models.CheckConstraint(
                condition=Q(fim__gt=models.F("inicio")),
                name="bloqueio_agenda_fim_apos_inicio",
            )
        ]
        indexes = [models.Index(fields=["profissional", "inicio", "fim"])]

    def __str__(self):
        return f"{self.profissional.nome_exibicao} — {self.inicio:%d/%m/%Y %H:%M}"

    def clean(self):
        super().clean()
        errors = {}
        if self.profissional_id and self.barbearia_id:
            if self.profissional.barbearia_id != self.barbearia_id:
                errors["profissional"] = "O profissional pertence a outra barbearia."
            if self.profissional.papel != Usuario.Papel.BARBEIRO:
                errors["profissional"] = "Selecione um usuário com papel de barbeiro."
        if self.inicio and self.fim and self.fim <= self.inicio:
            errors["fim"] = "O fim do bloqueio deve ser posterior ao início."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Agendamento(models.Model):
    class Status(models.TextChoices):
        AGENDADO = "AGENDADO", "Agendado"
        CONFIRMADO = "CONFIRMADO", "Confirmado"
        EM_ATENDIMENTO = "EM_ATENDIMENTO", "Em atendimento"
        CONCLUIDO = "CONCLUIDO", "Concluído"
        CANCELADO = "CANCELADO", "Cancelado"
        FALTOU = "FALTOU", "Cliente faltou"

    class Origem(models.TextChoices):
        INTERNO = "INTERNO", "Criado pela barbearia"
        ONLINE = "ONLINE", "Agendamento on-line"

    class FormaPagamento(models.TextChoices):
        DINHEIRO = "DINHEIRO", "Dinheiro"
        PIX = "PIX", "PIX"
        CARTAO_DEBITO = "CARTAO_DEBITO", "Cartão de débito"
        CARTAO_CREDITO = "CARTAO_CREDITO", "Cartão de crédito"
        PENDENTE = "PENDENTE", "Pagamento pendente"

    barbearia = models.ForeignKey(
        Barbearia,
        on_delete=models.CASCADE,
        related_name="agendamentos",
    )
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        related_name="agendamentos",
    )
    profissional = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        related_name="agendamentos",
        limit_choices_to={"papel": Usuario.Papel.BARBEIRO},
    )
    servico = models.ForeignKey(
        Servico,
        on_delete=models.PROTECT,
        related_name="agendamentos",
    )
    inicio = models.DateTimeField()
    fim = models.DateTimeField(blank=True)
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.AGENDADO,
    )
    origem = models.CharField(
        max_length=10,
        choices=Origem.choices,
        default=Origem.INTERNO,
    )
    forma_pagamento = models.CharField(
        max_length=20,
        choices=FormaPagamento.choices,
        blank=True,
    )
    preco_cobrado = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    observacoes = models.TextField(blank=True)
    iniciado_em = models.DateTimeField(null=True, blank=True)
    concluido_em = models.DateTimeField(null=True, blank=True)
    comissao_percentual_aplicada = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    comissao_valor = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    token_publico = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        ordering = ["inicio"]
        verbose_name = "agendamento"
        verbose_name_plural = "agendamentos"
        indexes = [
            models.Index(fields=["barbearia", "inicio"]),
            models.Index(fields=["profissional", "inicio", "fim"]),
        ]

    def __str__(self):
        return f"{self.cliente} - {self.inicio:%d/%m/%Y %H:%M}"

    def clean(self):
        super().clean()

        if self.servico_id and self.inicio and not self.fim:
            self.fim = self.inicio + timedelta(minutes=self.servico.duracao_minutos)

        errors = {}
        for field_name in ("cliente", "profissional", "servico"):
            objeto = getattr(self, field_name, None)
            if objeto and self.barbearia_id and objeto.barbearia_id != self.barbearia_id:
                errors[field_name] = "O registro pertence a outra barbearia."

        if self.profissional_id and self.profissional.papel != Usuario.Papel.BARBEIRO:
            errors["profissional"] = "Selecione um usuário com papel de barbeiro."

        if self.inicio and self.fim and self.fim <= self.inicio:
            errors["fim"] = "O fim do atendimento deve ser posterior ao início."

        if errors:
            raise ValidationError(errors)

        if (
            self.barbearia_id
            and self.profissional_id
            and self.inicio
            and self.fim
            and self.status != self.Status.CANCELADO
        ):
            conflito = (
                Agendamento.objects.filter(
                    barbearia_id=self.barbearia_id,
                    profissional_id=self.profissional_id,
                    inicio__lt=self.fim,
                    fim__gt=self.inicio,
                )
                .exclude(pk=self.pk)
                .exclude(status=self.Status.CANCELADO)
                .exists()
            )
            if conflito:
                raise ValidationError(
                    {"inicio": "Este profissional já possui atendimento nesse horário."}
                )

    def save(self, *args, **kwargs):
        if self.servico_id and self.inicio:
            self.fim = self.inicio + timedelta(minutes=self.servico.duracao_minutos)
            if self.preco_cobrado is None:
                self.preco_cobrado = self.servico.preco
        if self.status == self.Status.EM_ATENDIMENTO and self.iniciado_em is None:
            self.iniciado_em = timezone.now()
        if self.status == self.Status.CONCLUIDO:
            if self.iniciado_em is None:
                self.iniciado_em = timezone.now()
            if self.concluido_em is None:
                self.concluido_em = timezone.now()
            if self.comissao_percentual_aplicada is None and self.profissional_id:
                self.comissao_percentual_aplicada = self.profissional.comissao_percentual
            if (
                self.comissao_valor is None
                and self.preco_cobrado is not None
                and self.comissao_percentual_aplicada is not None
            ):
                self.comissao_valor = (
                    self.preco_cobrado
                    * self.comissao_percentual_aplicada
                    / Decimal("100")
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.full_clean()
        return super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("agendamento_lista")


class NotificacaoWhatsApp(models.Model):
    class Tipo(models.TextChoices):
        CONFIRMACAO = "CONFIRMACAO", "Confirmação do agendamento"
        LEMBRETE_24H = "LEMBRETE_24H", "Lembrete de 24 horas"
        LEMBRETE_2H = "LEMBRETE_2H", "Lembrete de 2 horas"

    class Status(models.TextChoices):
        PENDENTE = "PENDENTE", "Pendente"
        ENVIANDO = "ENVIANDO", "Enviando"
        ENVIADA = "ENVIADA", "Enviada"
        FALHOU = "FALHOU", "Falhou"
        CANCELADA = "CANCELADA", "Cancelada"

    barbearia = models.ForeignKey(
        Barbearia,
        on_delete=models.CASCADE,
        related_name="notificacoes_whatsapp",
    )
    agendamento = models.ForeignKey(
        Agendamento,
        on_delete=models.CASCADE,
        related_name="notificacoes_whatsapp",
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    destinatario = models.CharField(max_length=20)
    agendada_para = models.DateTimeField()
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDENTE,
    )
    tentativas = models.PositiveSmallIntegerField(default=0)
    enviada_em = models.DateTimeField(null=True, blank=True)
    mensagem_id = models.CharField(max_length=255, blank=True)
    ultimo_erro = models.TextField(blank=True)
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["agendada_para"]
        verbose_name = "notificação do WhatsApp"
        verbose_name_plural = "notificações do WhatsApp"
        constraints = [
            models.UniqueConstraint(
                fields=["agendamento", "tipo"],
                name="whatsapp_tipo_unico_por_agendamento",
            )
        ]
        indexes = [
            models.Index(fields=["status", "agendada_para"]),
            models.Index(fields=["barbearia", "status"]),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.agendamento}"
