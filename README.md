# Monitor de lançamentos — Lucinei Automóveis

Verifica o estoque de https://lucineiautomoveis.com.br/ a cada ~5 minutos
(GitHub Actions) e envia push para o celular via [ntfy.sh](https://ntfy.sh)
quando um veículo novo é anunciado.

## Como funciona

1. `monitor.py` varre todas as páginas de `BuscadorVeiculo.aspx`.
2. Compara os códigos dos veículos com `estado/veiculos.json` (commitado no repo).
3. Veículo novo → push com modelo, ano, preço, foto e link do anúncio.
4. O workflow roda no cron `*/5 * * * *`. Na prática o GitHub atrasa execuções
   agendadas — espere intervalos reais de 5 a 15 minutos.

## Configuração

1. **iPhone**: instale o app **ntfy** (App Store) e assine o tópico secreto
   (o mesmo valor do Secret abaixo). O nome do tópico funciona como senha —
   use algo não adivinhável.
2. **GitHub**: repositório público (minutos de Actions ilimitados) com o
   Secret `NTFY_TOPIC` contendo o nome do tópico.
3. Pronto — o workflow agendado faz o resto. A primeira execução cria o
   estado e manda uma única notificação-resumo (sem spam dos 120+ veículos
   já anunciados).

## Rodar localmente

```bash
pip install -r requirements.txt
set NTFY_TOPIC=<seu-topico>   # PowerShell: $env:NTFY_TOPIC="<seu-topico>"
python monitor.py
```

Sem `NTFY_TOPIC` definido, as notificações são apenas impressas no console.

## Comportamentos de segurança

- Scrape com 0 veículos (site fora do ar / layout mudou) → o script sai com
  erro **sem tocar no estado**, e a execução fica vermelha no GitHub.
- Mais de 10 veículos novos numa execução → 1 push-resumo em vez de um por
  veículo (anti-spam e proteção contra anomalia de parse).
- O estado é cumulativo: veículo removido e reanunciado com o mesmo código
  não gera novo aviso.
