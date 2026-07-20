# Implantação em produção e WhatsApp

Este guia prepara uma instalação piloto do BarberFlow usando Docker,
PostgreSQL e o processador de notificações do WhatsApp.

## 1. Pré-requisitos

- Docker Desktop no Windows ou Docker Engine no Linux.
- Um domínio apontando para o servidor.
- Um proxy HTTPS do provedor, Caddy, Nginx ou serviço equivalente.
- Conta WhatsApp Business configurada na Meta para realizar envios reais.

## 2. Configuração do ambiente

Copie `.env.example` para `.env` e gere uma chave secreta:

```powershell
Copy-Item .env.example .env
py -c "import secrets; print(secrets.token_urlsafe(64))"
```

Edite `.env` e configure pelo menos:

```env
SECRET_KEY=cole-a-chave-gerada
DEBUG=False
ALLOWED_HOSTS=barberflow.seudominio.com
CSRF_TRUSTED_ORIGINS=https://barberflow.seudominio.com
POSTGRES_PASSWORD=use-uma-senha-longa-e-exclusiva
USE_WHITENOISE=True
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=3600
```

Não envie o arquivo `.env` para o Git e não compartilhe seus tokens.

## 3. Subir a aplicação

```powershell
docker compose up -d --build
docker compose exec web python manage.py criar_dados_demo
docker compose ps
```

O contêiner aplica as migrações automaticamente. O endpoint `/saude/` retorna
HTTP 200 quando a aplicação consegue acessar o banco.

Antes de atender clientes reais, remova os dados demonstrativos ou altere todas
as senhas criadas pelo comando de demonstração.

## 4. HTTPS

O contêiner web escuta na porta 8000. Configure o proxy reverso para encaminhar
o domínio HTTPS para essa porta e enviar o cabeçalho
`X-Forwarded-Proto: https`. Só habilite HSTS depois de confirmar que o domínio
funciona permanentemente em HTTPS.

## 5. Backup do PostgreSQL

Crie uma pasta local `backups` e gere o arquivo dentro do contêiner:

```powershell
New-Item -ItemType Directory -Force backups
docker compose exec db pg_dump -U barberflow -d barberflow -Fc -f /tmp/barberflow.dump
docker compose cp db:/tmp/barberflow.dump ./backups/barberflow.dump
```

Copie o backup para outro computador ou armazenamento protegido. Programe essa
rotina diariamente e teste a restauração periodicamente.

Para restaurar, faça primeiro um backup do banco atual. A restauração substitui
dados e deve ser executada somente com a aplicação parada:

```powershell
docker compose stop web whatsapp_worker
docker compose cp ./backups/barberflow.dump db:/tmp/barberflow.dump
docker compose exec db pg_restore -U barberflow -d barberflow --clean --if-exists /tmp/barberflow.dump
docker compose start web whatsapp_worker
```

## 6. Configuração do WhatsApp

Siga a [documentação da Meta Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api/)
para cadastrar o número e obter as credenciais. Depois, crie na Meta dois
modelos de mensagem em português (`pt_BR`). Os dois devem
possuir seis parâmetros no corpo, nesta ordem:

1. primeiro nome do cliente;
2. nome da barbearia;
3. data do atendimento;
4. horário;
5. serviço;
6. profissional.

Exemplo de confirmação:

```text
Olá, {{1}}! Seu horário na {{2}} foi agendado para {{3}} às {{4}}. Serviço: {{5}} com {{6}}.
```

Exemplo de lembrete:

```text
Olá, {{1}}! Lembrete da {{2}}: seu atendimento é em {{3}} às {{4}}. Serviço: {{5}} com {{6}}.
```

Depois da aprovação dos modelos, preencha `.env`:

```env
WHATSAPP_ENABLED=True
WHATSAPP_DRY_RUN=False
WHATSAPP_API_VERSION=versao-atual-da-graph-api
WHATSAPP_PHONE_NUMBER_ID=identificador-do-numero
WHATSAPP_ACCESS_TOKEN=token-permanente
WHATSAPP_LANGUAGE_CODE=pt_BR
WHATSAPP_TEMPLATE_CONFIRMACAO=nome_do_modelo_de_confirmacao
WHATSAPP_TEMPLATE_LEMBRETE=nome_do_modelo_de_lembrete
WHATSAPP_REMINDER_HOURS=24,2
```

Recrie os serviços depois de alterar as variáveis:

```powershell
docker compose up -d --force-recreate web whatsapp_worker
```

O `whatsapp_worker` consulta a fila a cada cinco minutos. Ele envia apenas para
clientes que autorizaram notificações, registra o identificador retornado pela
API e tenta novamente até três vezes quando ocorre falha.

Para validar sem enviar mensagens reais:

```env
WHATSAPP_ENABLED=True
WHATSAPP_DRY_RUN=True
```

Execute manualmente e confira o histórico no painel administrativo:

```powershell
docker compose exec web python manage.py processar_notificacoes_whatsapp
```

## 7. Verificação antes do piloto

- Trocar as senhas demonstrativas.
- Confirmar HTTPS e cookies seguros.
- Testar criação, cancelamento e lembretes com um número real autorizado.
- Confirmar backup e restauração.
- Monitorar logs com `docker compose logs -f web whatsapp_worker`.
- Definir responsável pelo atendimento quando um envio falhar.
- Entrar em **Página de agendamento** e preencher logomarca, endereço, contatos,
  horários, política de privacidade e política de cancelamento.
- Conferir a antecedência mínima, o intervalo dos horários e o limite de dias
  configurados para cada barbearia.
- Fazer um teste real do link público, guardar o link da reserva e validar o
  reagendamento e o cancelamento pelo cliente.

## 8. Atualização desta versão

Depois de baixar a versão mais recente, aplique a nova migração antes de abrir
o sistema:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

Em Docker, a migração é aplicada automaticamente pelo `entrypoint.sh` ao
recriar o serviço web.
