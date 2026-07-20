# Escopo do MVP — sistema de gestão para barbearias

## Objetivo

Entregar uma aplicação web responsiva que substitua agenda de papel e planilhas,
centralizando clientes, serviços e atendimentos. A primeira implantação será
validada em uma barbearia piloto antes da comercialização para outros clientes.

## Perfis de acesso

- **Proprietário:** configura a operação e consulta indicadores.
- **Recepcionista:** administra clientes, serviços e agendamentos.
- **Barbeiro:** consulta a própria agenda e atualiza as etapas do atendimento.

## Funcionalidades desta primeira entrega

- Autenticação com usuário e senha.
- Separação dos dados por barbearia.
- Cadastro e edição de clientes.
- Cadastro e edição de serviços, duração e preço.
- Agenda com criação, edição e cancelamento de atendimentos.
- Agenda visual diária por barbeiro e visão semanal.
- Filtros de agenda por profissional e situação do atendimento.
- Área do proprietário para configurar jornadas e intervalos da equipe.
- Cadastro de folgas, férias e bloqueios pela interface comum.
- Gerenciamento de barbeiros e recepcionistas, incluindo acesso e comissão.
- Redefinição de senha e desativação segura de funcionários.
- Validação contra dois atendimentos simultâneos para o mesmo barbeiro.
- Agendamento público sem login, com escolha de serviço, barbeiro e horário.
- Cálculo de disponibilidade usando jornadas, bloqueios e atendimentos existentes.
- Cópia do preço do serviço para preservar o valor praticado no agendamento.
- Painel com atendimentos, clientes ativos e faturamento concluído do dia.
- Tela operacional diária do barbeiro, com acesso apenas aos próprios clientes.
- Confirmação de chegada, início do atendimento e registro de falta.
- Conclusão com valor final, forma de pagamento e comissão congelada no histórico.
- Relatório financeiro com faturamento, ticket médio, comissões e valor líquido.
- Filtros financeiros por período, barbeiro e forma de pagamento.
- Distribuição dos recebimentos, comissões por profissional e exportação CSV.
- Consentimento e notificações de confirmação e lembrete pelo WhatsApp.
- Fila de mensagens com tentativas, histórico e execução automática.
- Estrutura de produção com PostgreSQL, Docker e endpoint de saúde.
- Painel administrativo para cadastrar barbearias e funcionários.

## Próximas entregas

1. Fechamento de caixa, despesas e comissões pagas.
2. Configurações de privacidade, exportação e exclusão de dados pessoais.
3. Cadastro comercial de novas barbearias, planos e cobrança recorrente.

## Critérios para o piloto

- Nenhum usuário pode acessar dados de outra barbearia.
- Não pode existir conflito de agenda para o mesmo profissional.
- Todas as ações comuns devem funcionar em celular e computador.
- O proprietário precisa conseguir entender a agenda do dia sem treinamento.
- Erros de cadastro devem ser explicados em linguagem clara.
