# BarberFlow

MVP de um sistema web para gestão de barbearias, criado com Python e Django
5.2 LTS.
Cada barbearia possui seu próprio conjunto de clientes, serviços, funcionários
e agendamentos.

## Funcionalidades atuais

- Login com perfis de proprietário, recepcionista e barbeiro.
- Painel com agenda e faturamento do dia.
- Agenda visual diária, com uma coluna por barbeiro.
- Agenda visual semanal, filtros por profissional e situação.
- Área de equipe para configurar jornadas, intervalos e dias sem expediente.
- Cadastro de folgas, férias e bloqueios sem usar o painel administrativo.
- Cadastro e edição de barbeiros e recepcionistas pela interface comum.
- Redefinição de senha, comissão e ativação ou desativação de acessos.
- Proteção do histórico e dos atendimentos futuros ao alterar funcionários.
- Tela operacional “Meu dia” exclusiva para cada barbeiro.
- Confirmação de chegada, início, conclusão e registro de falta do cliente.
- Registro do valor final, forma de pagamento e comissão do atendimento.
- Painel financeiro exclusivo do proprietário, com filtros por período,
  barbeiro e forma de pagamento.
- Indicadores de faturamento, ticket médio, comissões e valor líquido.
- Relatórios por dia, meio de pagamento e profissional, com exportação CSV.
- Consentimento do cliente e fila de confirmações e lembretes pelo WhatsApp.
- Processamento automático com histórico, repetição de falhas e modo de simulação.
- Configuração de produção com PostgreSQL, Docker, health check e segurança HTTPS.
- Cadastro de clientes e serviços.
- Criação, edição e cancelamento de agendamentos.
- Detecção de conflito de horários para o mesmo profissional.
- Link público para o cliente escolher serviço, barbeiro, data e horário.
- Cálculo dos horários disponíveis usando jornada, bloqueios e atendimentos.
- Interface responsiva para computador e celular.
- Painel administrativo do Django.
- Testes de isolamento dos dados e regras de agendamento.

O escopo completo do produto está em [`docs/MVP.md`](docs/MVP.md).
O guia de implantação está em [`docs/PRODUCAO.md`](docs/PRODUCAO.md).

## Executando no Linux ou WSL

Caso o ambiente ainda não possua os pacotes do Python:

```bash
sudo apt update
sudo apt install python3-venv python3-pip
```

Depois, dentro da pasta do projeto:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 manage.py migrate
python3 manage.py criar_dados_demo
python3 manage.py runserver
```

Acesse `http://127.0.0.1:8000`.

Página pública de demonstração:

```text
http://127.0.0.1:8000/agendar/barbearia-demo/
```

## Executando no Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py criar_dados_demo
.\.venv\Scripts\python.exe manage.py runserver
```

Esses comandos não precisam ativar o ambiente virtual no PowerShell.

## Acesso de demonstração

- Gestor: `gestor` / `Barbearia123!`
- Barbeiro: `barbeiro` / `Barbearia123!`

Ao entrar como barbeiro, o sistema abre automaticamente a tela operacional em
`http://127.0.0.1:8000/meu-dia/`.

Essas credenciais são somente para desenvolvimento. Altere-as antes de
publicar a aplicação.

## Testes

```bash
python3 manage.py test
```

## Estrutura

```text
barbearia/       configurações e rotas gerais
gestao/          modelos, formulários, telas e regras do negócio
static/          estilos da interface
docs/            escopo e decisões do produto
```

## Próxima etapa

Validar o sistema em uma barbearia piloto e implementar fechamento de caixa,
despesas e controle de comissões pagas.
