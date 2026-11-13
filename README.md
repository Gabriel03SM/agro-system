# 🌾 Agro Gestão — sistema de gestão interna para agropecuária

Django + PostgreSQL (Supabase) + deploy no Render.

**O que faz:** produtos, clientes e fornecedores; vendas com código de barras, descontos e pagamentos divididos; fiado com baixa parcial/total; estoque por lote e validade; abertura e fechamento de caixa; contas a pagar; relatórios CSV/PDF; importação CSV; comprovante não fiscal e histórico de alterações.

**Perfis:** gerente gerencia a loja e os acessos; caixa registra vendas, fiado e movimentações; estoquista cuida dos produtos, fornecedores e lotes. Os acessos são configurados em **Usuários**.

---

## Rodar no seu computador

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```
Abra http://127.0.0.1:8000. Sem `DATABASE_URL` no `.env`, usa SQLite local. Testes: `python manage.py test` (usa configuração e banco isolados).

---

## Deploy (Supabase + Render)

### 1) Subir o código no GitHub
Crie um repositório e envie esta pasta (o `.gitignore` já protege `.env` e `db.sqlite3`).

### 2) Banco no Supabase
1. Crie o projeto em supabase.com e guarde a senha do banco.
2. Clique em **Connect** → aba **Connection string** → escolha **Session pooler** e copie a URL:
   `postgresql://postgres.SEUREF:SENHA@aws-0-REGIAO.pooler.supabase.com:5432/postgres`
3. Se a senha tiver caracteres especiais (`@ # / ? :`), troque por código URL (ex.: `@` → `%40`).

> Use o **Session pooler**, não a "Direct connection": o Render free só tem IPv4 e a conexão direta do Supabase é IPv6. Se usar o Transaction pooler (porta 6543), o projeto já se ajusta sozinho.

### 3) Web service no Render
1. **New → Blueprint** e escolha o repositório (o `render.yaml` configura tudo) — ou **New → Web Service** manualmente com:
   - Build Command: `./build.sh`
   - Start Command: `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT`
2. Preencha as variáveis de ambiente:

| Variável | Valor |
|---|---|
| `DATABASE_URL` | URL do Session pooler do Supabase |
| `DJANGO_SUPERUSER_USERNAME` | usuário do gerente (ex.: `gerente`) |
| `DJANGO_SUPERUSER_PASSWORD` | senha forte |
| `DJANGO_SUPERUSER_EMAIL` | seu e-mail (opcional) |
| `NOME_LOJA` | nome que aparece no sistema |
| `SECRET_KEY` | gerada automática pelo `render.yaml` (manual: string longa e aleatória) |
| `DEBUG` | `False` |
| `PYTHON_VERSION` | `3.12.7` |

3. Faça o deploy. A cada deploy o `build.sh` instala dependências, coleta estáticos, aplica migrações, ativa a segurança RLS no Supabase e cria o gerente (só se ainda não existir).
4. Acesse a URL `https://SEU-APP.onrender.com`, entre com o gerente e crie os funcionários em **Usuários**, escolhendo caixa ou estoquista.

### Segurança no Supabase
O comando `ativar_rls` (já no build) liga o Row Level Security em todas as tabelas, bloqueando acesso pela API pública do Supabase. O Django conecta com o usuário `postgres` e continua funcionando. Não compartilhe a senha do banco.

### Limitações dos planos gratuitos
- Render free "dorme" após ~15 min sem acesso (primeira abertura demora ~50 s).
- Supabase free pausa o projeto após 7 dias sem uso e não garante backup diário: para uso real, considere planos pagos ou exportar backups periódicos (`pg_dump`).

---

## Estrutura
```
config/   configurações, urls, wsgi
loja/     models, services (regras de estoque), views, forms, admin, tests
templates/ static/   telas, CSS e JS da venda
build.sh  render.yaml  requirements.txt  .env.example
```

## Fluxo de dados
- **Venda** → baixa estoque (bloqueia se faltar) e entra no caixa (exceto **fiado**, que aparece como "a receber").
- **Cancelar venda** (gerente) → devolve o estoque e sai dos totais.
- **Recebimento de fiado** → abra a ficha do cliente e registre o valor recebido, total ou parcial. O sistema baixa as dívidas mais antigas e lança uma única entrada no caixa.
- **Saída de caixa** → fornecedor, despesa, salário, retirada etc.
- **Estoque** → entrada de mercadoria, perda e contagem em "Ajustar estoque"; tudo fica no histórico.

## Evolução e operação
Consulte [o acompanhamento das três fases](docs/IMPLEMENTACAO.md). Abra o caixa com o troco inicial antes de vender. Ao registrar entrada de mercadoria, selecione o fornecedor e o custo unitário. A conferência de fechamento considera somente dinheiro físico; Pix e cartões continuam no saldo financeiro do período.

Testes isolados: `python manage.py test --settings=config.test_settings`.

Para ativar backup, monitoramento, instalar no celular e configurar domínio, siga [o guia de produção](docs/PRODUCAO.md). Os agendamentos dependem de os workflows estarem na branch padrão; o backup também exige uma credencial de banco e uma chave pública configuradas no GitHub.
