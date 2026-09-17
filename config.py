"""
Configuração central do Dashboard de Eventos Corporativos.

Regra de governança: TODO nome de coluna, índice de coluna e mapeamento de
status vive AQUI, em um único lugar. Se a equipe que alimenta a planilha
renomear uma coluna ou adicionar uma nova, o ajuste é feito neste arquivo,
não espalhado pelo código do dashboard.
"""

# ---------------------------------------------------------------------------
# 1. FONTE DE DADOS
# ---------------------------------------------------------------------------

# ID da planilha (extraído da URL: .../spreadsheets/d/<SPREADSHEET_ID>/edit)
SPREADSHEET_ID = "1KJ4djTGvyZ3I9PyaLTyYNQXlyJ1rrPP5Xb2a3tMKR6g"

# Nomes exatos das abas na planilha (case-sensitive)
SHEET_EVENTOS = "EVENTOS CORP"
SHEET_RESUMO = "RESUMO"

# Método de leitura: endpoint público "gviz" do Google Sheets.
# Funciona SEM credencial/Service Account, desde que o compartilhamento da
# planilha esteja configurado como "Qualquer pessoa com o link pode
# visualizar". Não expõe a planilha na busca do Google, apenas para quem
# tem o link — mesmo nível de acesso que já existe hoje para a equipe que
# alimenta a base.
GVIZ_URL_TEMPLATE = (
    "https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    "/gviz/tq?tqx=out:csv&sheet={sheet_name}"
)

# ---------------------------------------------------------------------------
# 2. MAPEAMENTO DE COLUNAS — Aba "EVENTOS CORP"
# ---------------------------------------------------------------------------
# A planilha tem cabeçalhos mesclados/vazios em várias colunas (comum em
# planilhas mantidas manualmente). Por isso o mapeamento é por POSIÇÃO
# (índice 0-based), validado contra a estrutura real em 17/09/2026.
#
# ATENÇÃO (premissa a validar com a equipe): se alguém inserir ou remover
# uma coluna no meio da aba EVENTOS CORP, estes índices ficam desalinhados
# e o dashboard passa a ler dados errados SEM erro aparente. O loader roda
# uma validação de sanidade (ver data_loader.py) que aborta com uma
# mensagem clara caso a estrutura mude — mas o ideal, se a equipe topar,
# é migrar para cabeçalhos únicos de texto na aba (ex.: "PREVISAO_PAGAMENTO",
# "VALOR_PREVISTO") para eliminar esse risco por completo.

COL_MES_ANO = 0
COL_TEATRO = 1
COL_DATA_EVENTO = 2
COL_CLIENTE = 3
COL_PREVISAO_PAGAMENTO = 4   # data prevista de recebimento da parcela
COL_VALOR_PREVISTO = 5       # valor previsto da parcela/contrato
COL_HAVERA_REPASSE = 6       # "SIM"/"NÃO"
COL_VALOR_REPASSE = 7        # valor a repassar ao fornecedor
COL_STATUS = 8
COL_PAGO_EM = 9              # data efetiva do pagamento
COL_PARCELA = 10             # texto "n/N"
COL_SALDO_PAGO = 11          # valor efetivamente pago
COL_INSERIDO_SISTEMA = 12
COL_INSERIDO_FLUXO_CAIXA = 13
COL_OBS = 14  # opcional — nem sempre presente (ver nota abaixo); trata-se como "" quando ausente

EVENTOS_HEADER_ROWS = 2  # linhas de cabeçalho/totais a pular no topo da aba
# nº mínimo de colunas esperado (validação de sanidade). Validado contra o
# arquivo real baixado direto do Google Drive em 17/09/2026: a estrutura tem
# 14 colunas (0-13, sem OBS populada) — por isso o mínimo exigido é 14, não
# 15. Uma leitura via CSV público (gviz) pode devolver uma 15ª coluna (OBS)
# quando ela existe/está preenchida na planilha; o loader lida com os dois
# casos sem erro.
EVENTOS_MIN_COLS = 14

# ---------------------------------------------------------------------------
# 3. MAPEAMENTO — Aba "RESUMO" (metas por Teatro/Espaço)
# ---------------------------------------------------------------------------
RESUMO_COL_ESPACO = 1
RESUMO_COL_META = 2
RESUMO_COL_REALIZADO_SHEET = 3   # não usado como fonte de verdade (ver nota)
RESUMO_COL_PCT_META_SHEET = 4
RESUMO_COL_A_REALIZAR_SHEET = 5
RESUMO_COL_PCT_A_REALIZAR_SHEET = 6

RESUMO_HEADER_ROWS = 1
# A linha "Valor Total" e tudo abaixo dela (seção "TOTAL POR RESPONSAVEL")
# não são linhas de Teatro e devem ser ignoradas.
RESUMO_STOP_LABEL = "valor total"

# ACHADO DE QUALIDADE DE DADOS (validado contra a planilha real em
# 17/09/2026): a coluna "Saldo Pago" (COL_SALDO_PAGO) vem preenchida com o
# valor total da parcela mesmo em linhas cujo status ainda NÃO é PAGO —
# ela não distingue "recebido" de "a receber". O saldo em aberto é
# calculado em data_loader.py usando esse mesmo valor para linhas com
# status_grupo "Em aberto" (não por subtração de Valor Previsto - Saldo
# Pago, que sempre daria zero). Vale alinhar com a equipe se o nome da
# coluna pode ser ajustado para algo como "Valor da Parcela" — o nome
# atual induz ao erro.

# NOTA DE GOVERNANÇA (CFO): a aba RESUMO trai "R$ Realizado*" e "% Meta*"
# calculados manualmente por alguém na equipe. Este dashboard NÃO usa essas
# colunas como fonte de verdade para "Realizado" — em vez disso, recalcula
# o Realizado somando "Saldo Pago" da aba EVENTOS CORP (linha a linha,
# respeitando os filtros aplicados). Isso elimina uma segunda fonte de
# verdade que pode divergir silenciosamente do detalhe operacional.
# A Meta (coluna B) continua vindo da aba RESUMO, pois esse é um valor de
# input estratégico, não um cálculo derivável do operacional.

# ---------------------------------------------------------------------------
# 4. NORMALIZAÇÃO DE STATUS
# ---------------------------------------------------------------------------
# Valores reais observados na planilha em 17/09/2026 (não são os mesmos do
# briefing original "Pago/Pendente/Atrasado/Cancelado" — mapeados abaixo).
STATUS_PAGO = "PAGO"
STATUS_AGUARDANDO = "AGUARDANDO PAGAMENTO"
STATUS_ATRASADO = "EM ATRASO"
STATUS_CANCELADO = "CANCELADO"
STATUS_NOVO = "EVENTO NOVO"

STATUS_CANONICOS = [STATUS_PAGO, STATUS_AGUARDANDO, STATUS_ATRASADO, STATUS_CANCELADO, STATUS_NOVO]

# Grupos usados nos KPIs:
STATUS_QUE_CONTAM_COMO_RECEITA_REALIZADA = [STATUS_PAGO]
STATUS_QUE_CONTAM_COMO_EM_ABERTO = [STATUS_AGUARDANDO, STATUS_ATRASADO, STATUS_NOVO]
STATUS_EXCLUIDOS_DE_PROJECAO = [STATUS_CANCELADO]  # contratos cancelados não entram em nenhuma soma de receita

# ---------------------------------------------------------------------------
# 5. CACHE
# ---------------------------------------------------------------------------
CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h — atende ao requisito de refresh diário
