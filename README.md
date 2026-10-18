# Monitor de passagens Azul com pontos

Aplicação para monitorar o preço em pontos (TudoAzul) das passagens da Azul. Você informa a
rota e o período de datas, e ela consulta os preços automaticamente, guarda o histórico e
envia um alerta quando aparece um bom preço.

## Como funciona

- **Monitores:** cada monitor tem origem, destino, um período de datas de ida (até 60 dias), a
  frequência de verificação e as regras de alerta.
- **Bom preço:** a aplicação alerta quando a melhor oferta de uma data
  - custa até o limite de pontos que você definiu, **ou**
  - está pelo menos X% abaixo da média histórica do monitor (padrão: 20%).

  Para não repetir avisos, uma data só gera novo alerta quando o preço cai abaixo do último
  preço alertado.
- **Alertas:** console (sempre), Telegram, e-mail e [ntfy](https://ntfy.sh) (notificação no
  celular). Configure no `.env`.
- **Interface web:** cadastro de monitores, melhor preço por data, gráfico da evolução e
  histórico de alertas.

## Instalação

Requer Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env             # depois edite o .env
```

## Uso

```bash
# Interface web + verificações automáticas: abra http://127.0.0.1:8000
python -m azul_monitor servir

# Busca avulsa de uma data
python -m azul_monitor buscar VCP REC 2026-12-20

# Verifica todos os monitores ativos uma vez (útil para agendar no cron)
python -m azul_monitor verificar
```

Para testar sem acessar o site da Azul, use preços fictícios:

```bash
AZUL_PROVEDOR=simulado python -m azul_monitor servir
```

A aplicação precisa ficar rodando para monitorar. Deixe-a num computador sempre ligado, num
servidor ou numa VPS, ou agende `python -m azul_monitor verificar` no cron.

## Rodar no GitHub (sem computador ligado)

O workflow `.github/workflows/monitor.yml` roda a verificação no GitHub Actions a cada 3
horas. A interface web não roda no GitHub; no lugar dela há um relatório em Markdown.

1. **Escolha as rotas** editando `monitores.json` (pode ser direto no site do GitHub, no ícone
   de lápis). Cada item é um monitor:

   ```json
   [
     {"origem": "VCP", "destino": "REC", "data_inicio": "2026-12-15", "data_fim": "2026-12-22",
      "max_pontos": 15000, "desconto_minimo_pct": 20, "somente_diretos": false}
   ]
   ```

   Monitores removidos do arquivo são pausados (o histórico é mantido).

2. **Configure os alertas** em *Settings → Secrets and variables → Actions → New repository
   secret*. Use os mesmos nomes do `.env.example`: `TELEGRAM_TOKEN` e `TELEGRAM_CHAT_ID`,
   `NTFY_TOPIC`, ou `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_DESTINO`.

3. **Rode a primeira vez** na aba *Actions → Monitor de passagens Azul → Run workflow*. Depois
   ele roda sozinho no horário agendado.

4. **Veja os preços** no resumo de cada execução (aba *Actions*) ou no arquivo
   `dados/RELATORIO.md`, atualizado a cada execução junto com o histórico
   (`dados/azul_monitor.db`).

Observações:

- Para mudar a frequência, edite a linha `cron` do workflow (horário UTC). O GitHub pode atrasar
  execuções agendadas em alguns minutos e as desativa após 60 dias sem commits no repositório.
- Para testar com preços fictícios, crie a variável `AZUL_PROVEDOR` com valor `simulado` em
  *Settings → Secrets and variables → Actions → Variables*.
- Se a busca falhar, cada execução guarda as respostas do site por 7 dias, em *Artifacts* →
  `respostas-azul`.
- O site da Azul pode bloquear acessos vindos de servidores do GitHub. Se isso acontecer, rode a
  aplicação num computador seu.
- Em repositório público, `monitores.json` e o relatório ficam visíveis para qualquer pessoa.
  Os secrets não ficam.

## Sobre a consulta ao site da Azul

A Azul não oferece API pública para resgate com pontos. O provedor `azul`
(`azul_monitor/providers/azul.py`) abre a página de seleção de voos num navegador real com a
busca em pontos e lê as respostas JSON que o próprio site recebe. Pontos de atenção:

- O formato dessas respostas não é documentado e pode mudar. O parser procura os valores em
  pontos sem depender de um esquema fixo, mas se as buscas pararem de retornar ofertas, defina
  `AZUL_DEBUG_DIR=debug`, rode uma `buscar` e use os arquivos salvos para ajustar
  `extrair_ofertas`.
- O site pode ter proteção anti-robô. Se as buscas falharem, tente `AZUL_HEADLESS=0` (abre o
  navegador visível) e frequências menores.
- Use com moderação: a aplicação faz uma busca por data e espera `AZUL_PAUSA_SEGUNDOS` entre
  elas. Verifique os termos de uso do site; esta ferramenta é para uso pessoal.

Os preços exibidos são os da última consulta. Confirme sempre no site antes de emitir.

## Testes

```bash
python -m pytest
```

## Estrutura

```
azul_monitor/
  __main__.py        linha de comando
  web.py             interface web (FastAPI) e agendador
  monitor.py         verificação dos monitores e regra de "bom preço"
  alertas.py         Telegram, e-mail, ntfy
  relatorio.py       relatório em Markdown (usado no GitHub)
  db.py              SQLite: monitores, histórico de preços, alertas
  providers/
    azul.py          consulta ao site da Azul (Playwright)
    simulado.py      preços fictícios para testes
tests/
monitores.json       rotas monitoradas no GitHub Actions
.github/workflows/   agendamento no GitHub Actions
```
