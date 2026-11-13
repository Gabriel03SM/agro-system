# Evolução do Agro Gestão

Repositório: Gabriel03SM/agro-system. Produção atual: https://agro-gestao.onrender.com/ (Render + Supabase).

## Fase 1 — operação

Implementada e validada: clientes e fiado com recebimento parcial/total; fornecedores e entrada com custo; busca por produto e leitor de código USB/Bluetooth; descontos em reais por item/venda; pagamentos divididos; abertura e conferência de caixa; comprovante não fiscal; correção de vendas com histórico e controle de versão.

As vendas e os lançamentos de um caixa fechado ficam preservados. Um gerente pode corrigir vendas de um caixa aberto; recebimentos existentes impedem trocar o cliente ou reduzir o fiado abaixo do que já foi pago.

A migração preserva as vendas e cria clientes a partir dos nomes antigos. Nomes iguais são agrupados; cabe conferir homônimos. Recebimentos avulsos anteriores não têm cliente identificável: o gerente deve vinculá-los na ficha do cliente, na opção de conferência de recebimentos anteriores. Isso evita duplicar o dinheiro no caixa.

## Fase 2 — gestão

Em implementação: relatórios com CSV/PDF, lote e validade, contas a pagar, importação CSV, perfis gerente/caixa/estoquista e auditoria.

## Fase 3 — produção

Pendente: backup automático, monitoramento, proteção de login/senhas, PWA/layout móvel, GitHub Actions e testes das telas novas.

Ainda não há domínio próprio comprado. As configurações dependentes de serviços externos e secrets serão documentadas; não são consideradas ativas sem verificação no serviço.

## Validação

`python manage.py test --settings=config.test_settings`

O ambiente de testes usa banco isolado e um hash de senha rápido exclusivamente para testes. Nunca use `config.test_settings` no Render.
