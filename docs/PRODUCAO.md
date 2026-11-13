# Produção e operação

Serviço atual: https://agro-gestao.onrender.com/ (Render + Supabase).

## Publicar esta versão

1. Confira o resultado de **Testes** no GitHub. A execução cobre PostgreSQL, fluxos reais no Chromium e exportação/restauração/cifragem de um banco de teste.
2. Antes de aplicar as migrações em produção, tire uma cópia do banco atual e preserve-a.
3. Incorpore a branch revisada à `main` e sincronize o Blueprint do Render. O `render.yaml` usa `autoDeployTrigger: checksPass` para aguardar os checks do GitHub. Em serviços criados manualmente, configure **Auto-Deploy > After CI Checks Pass** no painel.
4. O build aplica as migrações e ativa RLS nas tabelas novas. Confira `/healthz`, `/readyz` e o login após o deploy.
5. Confira os clientes criados a partir dos nomes antigos e vincule recebimentos avulsos antigos pela ficha do cliente, sem duplicar entradas.
6. Crie os perfis em **Usuários**. Usuários comuns anteriores passam a caixa; gerentes existentes continuam gerentes.

Referência: [Blueprints e checks do Render](https://render.com/docs/blueprint-spec#autodeploytrigger).

## Backup diário fora do Supabase

O workflow `backup.yml` roda às 06:37 UTC (03:37 em São Paulo). Exporta somente as tabelas da aplicação Django (`loja_*`, `auth_*`, `django_*`, `axes_*` no schema public), restaura a cópia em PostgreSQL efêmero para testar a integridade e cifra o arquivo com age antes de enviá-lo aos artefatos do GitHub. Mantém os arquivos cifrados por 14 dias.

Isso cobre os dados usados por esta aplicação. Não exporta Supabase Auth, Storage, arquivos de outros sistemas nem a configuração inteira do projeto Supabase.

### Ativar

1. Instale [age](https://github.com/FiloSottile/age/releases) em um computador sob seu controle e gere um par de chaves:

   ```bash
   age-keygen -o backup-chave.agekey
   age-keygen -y backup-chave.agekey
   ```

2. Guarde a chave privada `backup-chave.agekey` fora do repositório, com uma cópia protegida em outro local. O CI recebe somente a chave pública que começa com `age1`.
3. No GitHub, entre em **Settings > Secrets and variables > Actions**:

   | Tipo | Nome | Conteúdo |
   |---|---|---|
   | Secret | `BACKUP_DATABASE_URL` | URL PostgreSQL direta ou Session pooler do Supabase, com senha codificada na URL |
   | Variable | `BACKUP_AGE_RECIPIENT` | Chave pública `age1...` |

4. Use Session pooler na porta 5432 para compatibilidade IPv4. Não use Transaction pooler (6543). O cliente `pg_dump` usado é PostgreSQL 18; deve ter versão igual ou superior ao servidor.
5. Depois de o workflow estar na `main`, abra **Actions > Backup diário cifrado > Run workflow**. Só considere o backup ativo após uma execução de sucesso com o artefato anexado.

O workflow falha explicitamente se faltarem as configurações. Não existe chave privada no servidor ou nos workflows. Os artefatos são cifrados porque o repositório é público. Baixe cópias para retenção maior que 14 dias e acompanhe as execuções agendadas.

### Restaurar uma cópia

Baixe o artefato cifrado e confira o SHA-256 antes de abrir:

```bash
sha256sum --check agro-AAAAMMDDTHHMMSSZ.dump.age.sha256
age --decrypt -i backup-chave.agekey -o banco.dump agro-AAAAMMDDTHHMMSSZ.dump.age
pg_restore --list banco.dump
```

Restaure primeiro em um banco novo e vazio, nunca diretamente sobre o banco em uso. Forneça `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` e `PGSSLMODE` pelo ambiente e rode:

```bash
pg_restore --exit-on-error --single-transaction --no-owner --no-acl --dbname "$PGDATABASE" banco.dump
```

Valide usuários, vendas, pagamentos, estoque e migrações na cópia restaurada. O procedimento de produção exige decidir a janela de troca e a conexão do serviço; não há restauração automática sobre dados em uso.

Referências: [backups do Supabase](https://supabase.com/docs/guides/platform/backups), [conexões e poolers](https://supabase.com/docs/guides/database/connecting-to-postgres).

## Monitoramento e inatividade

`monitor.yml` consulta `/readyz` a cada 10 minutos, com tentativas adicionais para o tempo de inicialização do Render. `/readyz` verifica aplicação e conexão com o banco; `/healthz` verifica somente o processo.

A variável opcional do GitHub `PUBLIC_SITE_URL` altera a origem monitorada. O padrão já é `https://agro-gestao.onrender.com`.

Agendamentos do GitHub podem atrasar e são desativados em repositórios públicos após 60 dias sem atividade. Portanto, esses pings ajudam com a inatividade e detectam falhas, mas não garantem que o serviço gratuito ficará sempre acordado. Para um monitor contínuo, configure um HTTP monitor no UptimeRobot para `https://agro-gestao.onrender.com/readyz`, a cada 5 minutos. Um plano pago do Render elimina o desligamento por inatividade; nenhuma contratação foi feita por esta alteração.

Referências: [agendamentos do GitHub](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), [limites do Render gratuito](https://render.com/docs/free), [UptimeRobot](https://uptimerobot.com/api/).

## Login e senhas

- Cinco tentativas inválidas bloqueiam temporariamente o usuário ou IP por 15 minutos; uma autenticação correta zera as falhas anteriores.
- As tentativas ficam no PostgreSQL, sobrevivendo a reinícios do Render. A configuração não depende de cache em memória.
- Novas senhas exigem pelo menos 12 caracteres e três tipos de caracteres, ou uma frase de pelo menos 20 caracteres, além das validações de senha comum e semelhança com o usuário.
- Senhas existentes continuam funcionando; troque senhas fracas em **Usuários**.
- Para liberar um usuário antes do prazo, um administrador autorizado pode usar `python manage.py axes_reset_username NOME` em um ambiente com a conexão configurada, ou o painel Admin de tentativas.

O host externo do Render determina a interpretação do proxy. O bloqueio por usuário permanece mesmo se o navegador trocar o cabeçalho de IP.

Os checks opcionais de HSTS para todos os subdomínios e inclusão em listas de preload permanecem desativados: ainda não há domínio próprio para confirmar que todos os subdomínios usam HTTPS.

Referência: [django-axes](https://django-axes.readthedocs.io/en/stable/2_installation.html).

## Instalar no celular

No Chrome/Android, abra o serviço por HTTPS e use **Instalar no celular** quando o navegador oferecer a instalação, ou o menu do navegador. No Safari/iPhone, use **Compartilhar > Adicionar à Tela de Início**.

A PWA armazena somente arquivos públicos da interface e uma página sem conexão. Vendas, fiados, dados de clientes e relatórios não ficam no cache. Operações financeiras precisam de internet e não são enfileiradas offline.

## Domínio da loja

Ainda não foi informado ou comprado um domínio. Quando tiver um:

1. Adicione-o em **Render > agro-gestao > Settings > Custom Domains**.
2. Configure os registros DNS exatos exibidos pelo Render e aguarde a validação e o certificado HTTPS.
3. No Render, defina `PUBLIC_BASE_URL=https://SEU-DOMINIO` (sem caminho), sincronize o Blueprint sem sobrescrever esse valor e publique a versão.
4. Atualize a variável do GitHub `PUBLIC_SITE_URL` e confirme login, formulários, `/readyz` e a instalação da PWA no novo endereço.

`PUBLIC_BASE_URL` configura os hosts e as origens CSRF. A URL `onrender.com` continua permitida, para migração sem interromper o acesso existente.
