# Dashboard de Vendas — Eventos Corporativos
Associação As Teatrais

## 1. Pré-requisito na planilha (fazer ANTES de tudo)

O dashboard lê a planilha pelo endpoint público do Google Sheets (`gviz`), sem
Service Account. Para isso funcionar:

1. Abra a planilha `[OFICIAL] - EVENTOS CORP 2026`.
2. **Compartilhar** → **Acesso geral** → mude para **"Qualquer pessoa com o
   link" / "Leitor"**.
3. Confirme que os nomes das abas continuam exatamente `EVENTOS CORP` e
   `RESUMO` (o código depende do nome exato, incluindo maiúsculas).

**Risco a avaliar com a diretoria:** isso torna a planilha legível por
qualquer pessoa que tenha o link (não aparece em buscas, mas também não
exige login Google). Se a receita por cliente for informação sensível
demais para esse nível de exposição, a alternativa é migrar para
**Service Account** (autenticação via credencial), que é mais segura porém
exige um passo extra de configuração (posso preparar essa versão se
decidirem por ela — é uma troca de poucas linhas em `data_loader.py`).

## 2. Estrutura de arquivos

```
dashboard/
├── app.py            # Dashboard Streamlit (interface, filtros, gráficos)
├── data_loader.py     # ETL: download, limpeza, cálculo de KPIs derivados
├── config.py           # TODO mapeamento de colunas e regras de negócio fica aqui
├── requirements.txt
└── README.md            # este arquivo
```

**Toda premissa de negócio está documentada em `config.py`**, incluindo:
- Índices das colunas da aba `EVENTOS CORP` (a aba tem cabeçalhos
  mescladas/vazios; o mapeamento é por posição, validado em 17/09/2026).
- Os status reais encontrados na planilha (`PAGO`, `AGUARDANDO PAGAMENTO`,
  `EM ATRASO`, `CANCELADO`, `EVENTO NOVO`) — **diferentes** dos nomes do
  briefing original (Pago/Pendente/Atrasado/Cancelado). O dashboard já usa
  os nomes reais.
- A decisão de recalcular "Realizado" a partir do detalhe operacional
  (soma de `Saldo Pago`), em vez de usar a coluna `R$ Realizado*` da aba
  `RESUMO`, que é preenchida manualmente e pode divergir do operacional.

**Se a equipe inserir ou remover uma coluna no meio da aba `EVENTOS CORP`**,
os índices em `config.py` ficam desalinhados. O `data_loader.py` faz uma
validação de sanidade (número mínimo de colunas) e falha com uma mensagem
clara em vez de mostrar números errados silenciosamente — mas vale revisar
`config.py` após qualquer mudança estrutural na planilha.

## 3. Rodar localmente

```bash
cd dashboard
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Abre em `http://localhost:8501`.

### Testar sem depender da rede (dados de exemplo)
```bash
export DASHBOARD_TEST_CSV_EVENTOS=caminho/para/eventos_mock.csv
export DASHBOARD_TEST_CSV_RESUMO=caminho/para/resumo_mock.csv
streamlit run app.py
```

## 4. Atualização diária dos dados

- O app usa `@st.cache_data(ttl=86400)` — os dados são buscados no Google
  Sheets automaticamente a cada 24h, sem nenhuma ação manual.
- Qualquer pessoa pode forçar uma atualização imediata clicando em
  **"🔄 Forçar atualização"** no topo do dashboard (útil no dia em que a
  equipe acabou de lançar dados novos e alguém quer ver na hora).
- Não há job/cron externo necessário: o próprio Streamlit gerencia o cache
  por processo. Se o app "dormir" (plano gratuito do Streamlit Cloud
  hiberna após inatividade), o primeiro acesso do dia já vai buscar dados
  frescos ao "acordar".

## 5. Publicação (deploy)

### Opção recomendada: Streamlit Community Cloud (gratuito)

1. Suba esta pasta (`dashboard/`) para um repositório no GitHub (pode ser
   privado).
2. Acesse **share.streamlit.io** → **New app** → selecione o repositório,
   branch e o arquivo `app.py`.
3. Não é necessário configurar nenhum "Secret" nesta versão (não há
   credencial — o acesso é via link público da planilha, ver seção 1).
4. Deploy. A URL gerada (`https://<algo>.streamlit.app`) pode ser
   compartilhada com quem precisar acompanhar o dashboard.

Limitações a ter em mente: o plano gratuito hiberna o app após um período
sem acesso (volta ao acessar de novo, com uma pequena demora no primeiro
carregamento) e tem limite de recursos — adequado para o volume atual de
dados descrito no briefing (uma planilha, duas abas). Se o uso crescer
(muitos usuários simultâneos, ou a planilha ficar muito grande), migrar
para servidor próprio.

### Alternativa: servidor próprio (VPS/EC2)

```bash
# Exemplo com systemd (Linux)
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```
Rodar por trás de um Nginx com HTTPS (Let's Encrypt) e um serviço systemd
para manter o processo vivo e reiniciar em caso de falha. Recomendo essa
opção apenas se já existir infraestrutura própria a manter — Streamlit
Community Cloud resolve o requisito de "atualização diária/online" com
zero manutenção.

## 6. Recomendação do CFO

**Aprovar a arquitetura com uma condição**: validar com a equipe que
alimenta a planilha se os nomes e a ordem das colunas na aba `EVENTOS CORP`
vão permanecer estáveis — essa é a única dependência frágil da solução
(cabeçalhos mesclados/vazios exigem mapeamento por posição). Se a resposta
for "não temos controle sobre isso", a ação corretiva é padronizar
cabeçalhos de texto único na aba antes do lançamento, não depois.

Fora esse ponto, a solução está pronta para uso: custo zero de
infraestrutura (Streamlit Community Cloud), sem credencial para gerenciar,
refresh automático diário e failsafe que avisa (em vez de mascarar) quando
a estrutura da fonte de dados muda.
