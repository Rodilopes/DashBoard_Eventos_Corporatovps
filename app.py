"""
Dashboard de Vendas — Eventos Corporativos
Associação As Teatrais

Executar localmente:
    streamlit run app.py

Deploy: ver README.md (Streamlit Community Cloud).
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import config
from data_loader import BaseDados, FonteDadosError, EstruturaInvalidaError, carregar_tudo

# ---------------------------------------------------------------------------
# Configuração da página
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Eventos Corporativos — Dashboard de Vendas",
    page_icon="🎭",
    layout="wide",
)

CINZA = "#8892a0"
VERDE = "#1f9d55"
AMARELO = "#e0a800"
VERMELHO = "#d64545"
AZUL = "#2f6fed"


# ---------------------------------------------------------------------------
# Carga de dados (cacheada — refresh automático a cada 24h)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=config.CACHE_TTL_SECONDS, show_spinner="Buscando dados atualizados do Google Sheets...")
def carregar_dados_cache() -> BaseDados:
    caminho_teste_eventos = os.environ.get("DASHBOARD_TEST_CSV_EVENTOS")
    caminho_teste_resumo = os.environ.get("DASHBOARD_TEST_CSV_RESUMO")
    return carregar_tudo(caminho_teste_eventos, caminho_teste_resumo)


def formatar_moeda(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def formatar_moeda_compacta(v: float) -> str:
    """Formato executivo para KPIs de destaque: abrevia em Mil/Mi/Bi para
    caber no card sem truncar (ex.: 'R$ 4.163.234,50' -> 'R$ 4,16 Mi').
    Valores abaixo de R$ 1.000 continuam no formato completo — abreviar um
    valor pequeno tira precisão sem ganhar espaço."""
    sinal = "-" if v < 0 else ""
    v_abs = abs(v)
    # Arredondamento pode "estourar" a casa (ex.: 999.999 -> 1.000,0 Mil em
    # vez de 1,00 Mi) — escolhe a unidade pelo valor já arredondado na casa
    # de cima, não pelo valor bruto, para nunca mostrar "1.000 Mil"/"1.000 Mi".
    if round(v_abs / 1_000_000_000, 2) >= 1:
        texto = f"{v_abs / 1_000_000_000:,.2f} Bi"
    elif round(v_abs / 1_000_000, 2) >= 1:
        texto = f"{v_abs / 1_000_000:,.2f} Mi"
    elif round(v_abs / 1_000, 1) >= 1:
        texto = f"{v_abs / 1_000:,.1f} Mil"
    else:
        return formatar_moeda(v)
    texto = texto.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{sinal}R$ {texto}"


def formatar_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def titulo_caso(s: str) -> str:
    return str(s or "").title()


def texto_seguro(s: str) -> str:
    """Escapa '$' antes de passar por st.write/st.markdown — o Streamlit
    interpreta um par de '$' na mesma string como delimitador de LaTeX, o
    que quebra qualquer frase com duas ou mais menções a 'R$'."""
    return str(s).replace("$", "\\$")


_MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def rotulo_mes(chave: str) -> str:
    """'2026-05' -> 'mai/26'. Espelha monthLabel() do dashboard HTML."""
    ano, mes = chave.split("-")
    return f"{_MESES_ABREV[int(mes) - 1]}/{ano[2:]}"


# ---------------------------------------------------------------------------
# Carga + tratamento de erro (mensagens de ação clara, não stack trace)
# ---------------------------------------------------------------------------

col_titulo, col_refresh = st.columns([5, 1])
with col_titulo:
    st.title("🎭 Dashboard de Vendas — Eventos Corporativos")
    st.caption("Associação As Teatrais · Receita e projeção por Teatro/Espaço, Cliente e Status")
with col_refresh:
    if st.button("🔄 Forçar atualização", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

try:
    base = carregar_dados_cache()
except FonteDadosError as e:
    st.error(f"**Não foi possível ler a planilha.**\n\n{e}")
    st.stop()
except EstruturaInvalidaError as e:
    st.error(f"**A estrutura da planilha mudou.**\n\n{e}")
    st.stop()

eventos = base.eventos
metas = base.metas

st.caption(f"Última atualização dos dados: {base.carregado_em.strftime('%d/%m/%Y %H:%M')} "
           f"(cache renovado automaticamente a cada 24h, ou manualmente pelo botão acima)")

# ---------------------------------------------------------------------------
# Sidebar — Filtros
# ---------------------------------------------------------------------------

st.sidebar.header("Filtros")

# --- Filtro de período (sobre data_referencia: Pago em, senão Previsão) ---
hoje = date.today()
atalho = st.sidebar.radio(
    "Período",
    ["Este mês", "Próximo mês", "Ano atual", "Personalizado"],
    index=2,
)

if atalho == "Este mês":
    dt_ini = hoje.replace(day=1)
    proximo_mes = (dt_ini.replace(day=28) + timedelta(days=4)).replace(day=1)
    dt_fim = proximo_mes - timedelta(days=1)
elif atalho == "Próximo mês":
    prox = (hoje.replace(day=28) + timedelta(days=4)).replace(day=1)
    dt_ini = prox
    fim_prox = (prox.replace(day=28) + timedelta(days=4)).replace(day=1)
    dt_fim = fim_prox - timedelta(days=1)
elif atalho == "Ano atual":
    dt_ini = hoje.replace(month=1, day=1)
    dt_fim = hoje.replace(month=12, day=31)
else:
    intervalo = st.sidebar.date_input(
        "Intervalo personalizado",
        value=(hoje.replace(month=1, day=1), hoje.replace(month=12, day=31)),
    )
    if isinstance(intervalo, tuple) and len(intervalo) == 2:
        dt_ini, dt_fim = intervalo
    else:
        dt_ini, dt_fim = hoje.replace(month=1, day=1), hoje.replace(month=12, day=31)

teatros_disponiveis = sorted(eventos["teatro"].dropna().unique())
teatros_sel = st.sidebar.multiselect("Teatro / Espaço", teatros_disponiveis, default=teatros_disponiveis)

clientes_disponiveis = sorted(eventos["cliente"].dropna().unique())
clientes_sel = st.sidebar.multiselect("Cliente", clientes_disponiveis, default=[], placeholder="Todos os clientes")

status_disponiveis = sorted(eventos["status"].dropna().unique())
status_sel = st.sidebar.multiselect("Status", status_disponiveis, default=status_disponiveis)

st.sidebar.divider()
st.sidebar.caption(
    "**Nota metodológica:** o filtro de período é aplicado sobre a data de "
    "pagamento efetivo (quando já pago) ou sobre a previsão de pagamento "
    "(quando ainda pendente)."
)

# ---------------------------------------------------------------------------
# Aplicação dos filtros
# ---------------------------------------------------------------------------

f = eventos.copy()
if teatros_sel:
    f = f[f["teatro"].isin(teatros_sel)]
if clientes_sel:
    f = f[f["cliente"].isin(clientes_sel)]
if status_sel:
    f = f[f["status"].isin(status_sel)]

mask_periodo = f["data_referencia"].apply(
    lambda d: d is not None and dt_ini <= d <= dt_fim
)
f_periodo = f[mask_periodo].copy()

if f_periodo.empty:
    st.warning("Nenhum registro encontrado para os filtros selecionados.")

# ---------------------------------------------------------------------------
# Abas — Visão Geral / Por Status / Consistência de Dados / Insights
# ---------------------------------------------------------------------------

tab_geral, tab_status, tab_consistencia, tab_insights = st.tabs(
    ["📊 Visão Geral", "🏷️ Por Status", "⚠️ Consistência de Dados", "💡 Insights & Projeções"]
)

# =============================================================================
# ABA 1 — VISÃO GERAL
# =============================================================================
with tab_geral:
    # --- KPIs principais ----------------------------------------------------
    faturamento_realizado = f_periodo.loc[f_periodo["status_grupo"] == "Realizado", "valor_parcela"].sum()
    saldo_em_aberto = f_periodo.loc[f_periodo["status_grupo"] == "Em aberto", "saldo_em_aberto"].sum()
    projecao_futura = f_periodo.loc[
        (f_periodo["status_grupo"] == "Em aberto") & (f_periodo["previsao_pagamento"] >= hoje),
        "saldo_em_aberto",
    ].sum()

    meta_total = metas.loc[metas["teatro"].isin(teatros_sel), "meta"].sum() if teatros_sel else metas["meta"].sum()
    atingimento = (faturamento_realizado / meta_total) if meta_total > 0 else None

    n_eventos_pagos = f_periodo.loc[f_periodo["status_grupo"] == "Realizado"].shape[0]
    ticket_medio = (faturamento_realizado / n_eventos_pagos) if n_eventos_pagos > 0 else 0.0

    n_atrasados = f_periodo.loc[f_periodo["status"] == config.STATUS_ATRASADO].shape[0]

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Faturamento Realizado", formatar_moeda_compacta(faturamento_realizado),
              help=f"Valor exato: {formatar_moeda(faturamento_realizado)}")
    k2.metric(
        "Atingimento da Meta",
        formatar_pct(atingimento) if atingimento is not None else "—",
        help=f"Meta considerada: {formatar_moeda(meta_total)} (soma dos teatros filtrados, aba RESUMO)",
    )
    k3.metric("Saldo em Aberto", formatar_moeda_compacta(saldo_em_aberto),
              delta=f"{n_atrasados} contrato(s) em atraso" if n_atrasados else None, delta_color="inverse",
              help=f"Valor exato: {formatar_moeda(saldo_em_aberto)}")
    k4.metric("Projeção de Vendas Futuras", formatar_moeda_compacta(projecao_futura),
              help=f"Soma do saldo em aberto cuja previsão de pagamento é hoje ou no futuro. "
                   f"Valor exato: {formatar_moeda(projecao_futura)}")
    k5.metric("Ticket Médio (pago)", formatar_moeda_compacta(ticket_medio),
              help=f"Valor exato: {formatar_moeda(ticket_medio)}")

    st.divider()

    # --- Visão por Teatro: Realizado x Meta ---------------------------------
    col_a, col_b = st.columns([3, 2])

    with col_a:
        st.subheader("Desempenho por Teatro/Espaço — Realizado x Meta")
        realizado_por_teatro = (
            f_periodo.loc[f_periodo["status_grupo"] == "Realizado"]
            .groupby("teatro")["valor_parcela"].sum()
            .rename("realizado")
        )
        comp = metas.set_index("teatro").join(realizado_por_teatro, how="outer").fillna(0.0)
        if teatros_sel:
            comp = comp[comp.index.isin(teatros_sel)]
        comp = comp.reset_index().rename(columns={"index": "teatro"})
        comp["pct_atingimento"] = comp.apply(
            lambda r: (r["realizado"] / r["meta"]) if r["meta"] > 0 else float("nan"), axis=1
        )

        fig = go.Figure()
        fig.add_bar(name="Meta", x=comp["teatro"], y=comp["meta"], marker_color=CINZA)
        fig.add_bar(name="Realizado", x=comp["teatro"], y=comp["realizado"], marker_color=AZUL)
        fig.update_layout(barmode="group", yaxis_title="R$", legend_title="", height=420)
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.subheader("% Atingimento por Teatro")
        tabela_pct = comp[["teatro", "meta", "realizado", "pct_atingimento"]].copy()
        tabela_pct["pct_atingimento"] = tabela_pct["pct_atingimento"].map(
            lambda v: formatar_pct(v) if pd.notna(v) else "—"
        )
        tabela_pct["meta"] = tabela_pct["meta"].map(formatar_moeda)
        tabela_pct["realizado"] = tabela_pct["realizado"].map(formatar_moeda)
        tabela_pct.columns = ["Teatro", "Meta", "Realizado", "% Atingimento"]
        st.dataframe(tabela_pct, hide_index=True, use_container_width=True)

    st.divider()

    # --- Visão por Cliente ---------------------------------------------------
    col_c, col_d = st.columns(2)

    with col_c:
        st.subheader("Top Clientes — Faturamento Realizado")
        top_n = st.slider("Quantidade de clientes exibidos", 5, 30, 10, key="topn")
        por_cliente = (
            f_periodo.loc[f_periodo["status_grupo"] == "Realizado"]
            .groupby("cliente")["valor_parcela"].sum()
            .sort_values(ascending=False)
            .head(top_n)
            .reset_index()
        )
        fig_cli = px.bar(por_cliente, x="valor_parcela", y="cliente", orientation="h",
                          labels={"valor_parcela": "R$ Realizado", "cliente": ""}, color_discrete_sequence=[AZUL])
        fig_cli.update_layout(yaxis={"categoryorder": "total ascending"}, height=420)
        st.plotly_chart(fig_cli, use_container_width=True)

    with col_d:
        st.subheader("Saldo Não Pago por Cliente (Inadimplência/Pendências)")
        pendencias_cliente = (
            f_periodo.loc[f_periodo["status_grupo"] == "Em aberto"]
            .groupby("cliente")["saldo_em_aberto"].sum()
            .sort_values(ascending=False)
            .head(top_n)
            .reset_index()
        )
        if pendencias_cliente.empty:
            st.info("Sem saldo em aberto para os filtros selecionados.")
        else:
            fig_pend = px.bar(pendencias_cliente, x="saldo_em_aberto", y="cliente", orientation="h",
                               labels={"saldo_em_aberto": "R$ Em Aberto", "cliente": ""},
                               color_discrete_sequence=[VERMELHO])
            fig_pend.update_layout(yaxis={"categoryorder": "total ascending"}, height=420)
            st.plotly_chart(fig_pend, use_container_width=True)

    st.divider()

    # --- Evolução temporal: Realizado x Projetado ----------------------------
    st.subheader("Evolução Temporal — Realizado (Pago em) x Projetado (Previsão de Pagamento)")

    realizado_serie = (
        f.loc[f["status_grupo"] == "Realizado"]
        .assign(mes=lambda d: pd.to_datetime(d["pago_em"]).dt.to_period("M").astype(str))
        .groupby("mes")["valor_parcela"].sum()
        .rename("Realizado")
    )
    projetado_serie = (
        f.loc[f["status_grupo"] == "Em aberto"]
        .assign(mes=lambda d: pd.to_datetime(d["previsao_pagamento"]).dt.to_period("M").astype(str))
        .groupby("mes")["saldo_em_aberto"].sum()
        .rename("Projetado")
    )
    serie = pd.concat([realizado_serie, projetado_serie], axis=1).fillna(0.0).sort_index().reset_index()
    serie = serie.rename(columns={"index": "mes"})

    if serie.empty:
        st.info("Sem dados suficientes para a evolução temporal com os filtros atuais.")
    else:
        # Rótulo "mai/26" em vez de "2026-05" — mesmo formato usado no eixo X
        # do gráfico equivalente no Artifact HTML (monthLabel()).
        eixo_x = serie["mes"].map(rotulo_mes)
        fig_temp = go.Figure()
        fig_temp.add_scatter(x=eixo_x, y=serie["Realizado"], mode="lines+markers", name="Realizado",
                              line=dict(color=VERDE, width=3))
        fig_temp.add_scatter(x=eixo_x, y=serie["Projetado"], mode="lines+markers", name="Projetado",
                              line=dict(color=AMARELO, width=3, dash="dash"))
        fig_temp.update_layout(yaxis_title="R$", xaxis_title="Mês", height=420)
        st.plotly_chart(fig_temp, use_container_width=True)

    st.divider()

    # --- Saldo não pago & inadimplência — detalhe vencido x a vencer --------
    st.subheader("Saldo Não Pago & Inadimplência — Detalhe")

    detalhe = f_periodo.loc[f_periodo["status_grupo"] == "Em aberto"].copy()
    detalhe["situacao"] = detalhe["em_atraso_calculado"].map(lambda x: "Vencido" if x else "A vencer")

    resumo_venc = detalhe.groupby("situacao")["saldo_em_aberto"].sum().reindex(["Vencido", "A vencer"]).fillna(0.0)
    col_e, col_f = st.columns([1, 2])
    with col_e:
        fig_venc = px.pie(
            values=resumo_venc.values, names=resumo_venc.index,
            color=resumo_venc.index,
            color_discrete_map={"Vencido": VERMELHO, "A vencer": AMARELO},
            hole=0.5,
        )
        fig_venc.update_layout(height=320)
        st.plotly_chart(fig_venc, use_container_width=True)

    with col_f:
        tabela_detalhe = detalhe[[
            "cliente", "teatro", "status", "previsao_pagamento", "valor_parcela", "saldo_em_aberto", "situacao", "obs"
        ]].sort_values("saldo_em_aberto", ascending=False).copy()
        tabela_detalhe["valor_parcela"] = tabela_detalhe["valor_parcela"].map(formatar_moeda)
        tabela_detalhe["saldo_em_aberto"] = tabela_detalhe["saldo_em_aberto"].map(formatar_moeda)
        tabela_detalhe.columns = ["Cliente", "Teatro", "Status", "Previsão Pagamento", "Valor da Parcela", "Saldo em Aberto", "Situação", "Obs."]
        st.dataframe(tabela_detalhe, hide_index=True, use_container_width=True, height=320)

    st.caption(
        "Fonte: aba 'EVENTOS CORP' (base operacional) e aba 'RESUMO' (metas por Teatro/Espaço). "
        "A classificação de cada linha (Realizado / Em aberto / Cancelado) segue **exclusivamente** "
        "a coluna STATUS; o valor considerado é o da coluna 'Saldo Pago' (valor da parcela, incluindo "
        "repasse quando houver) — linhas onde os campos não batem entre si aparecem na aba "
        "**Consistência de Dados** em vez de serem corrigidas silenciosamente."
    )

# =============================================================================
# ABA 2 — POR STATUS
# =============================================================================
with tab_status:
    st.subheader("Visão por Status")
    st.caption(
        "O status de cada parcela é o único critério que decide se ela é receita realizada, "
        "em aberto ou cancelada — nenhum outro campo sobrepõe essa classificação."
    )

    status_ordem = [config.STATUS_PAGO, config.STATUS_AGUARDANDO, config.STATUS_ATRASADO,
                    config.STATUS_CANCELADO, config.STATUS_NOVO]
    total_geral = f_periodo["valor_parcela"].sum()

    cores_status = {
        config.STATUS_PAGO: VERDE,
        config.STATUS_AGUARDANDO: AMARELO,
        config.STATUS_ATRASADO: VERMELHO,
        config.STATUS_CANCELADO: CINZA,
        config.STATUS_NOVO: AZUL,
    }

    cols_status = st.columns(len(status_ordem))
    somas_status = {}
    for col, st_nome in zip(cols_status, status_ordem):
        sub = f_periodo.loc[f_periodo["status"] == st_nome]
        soma = sub["valor_parcela"].sum()
        n = sub.shape[0]
        pct = (soma / total_geral) if total_geral > 0 else 0.0
        somas_status[st_nome] = soma
        with col:
            st.markdown(f"**{st_nome}**")
            st.markdown(f"### {texto_seguro(formatar_moeda(soma))}")
            st.caption(f"{n} parcela(s) · {formatar_pct(pct)} do total")

    st.divider()

    fig_status = go.Figure()
    fig_status.add_bar(
        x=status_ordem, y=[somas_status[s] for s in status_ordem],
        marker_color=[cores_status[s] for s in status_ordem],
    )
    fig_status.update_layout(yaxis_title="R$", height=420)
    st.plotly_chart(fig_status, use_container_width=True)

# =============================================================================
# ABA 3 — CONSISTÊNCIA DE DADOS
# =============================================================================
with tab_consistencia:
    st.subheader("Consistência de Dados")
    st.caption("Linhas onde os campos da planilha se contradizem entre si — vale revisar com quem alimenta a base.")

    com_problema = f_periodo.loc[~f_periodo["consistente"]].copy()
    n_total = f_periodo.shape[0]
    n_problema = com_problema.shape[0]
    pct_problema = (n_problema / n_total) if n_total > 0 else 0.0
    valor_suspeito = com_problema["valor_parcela"].sum()

    todos_motivos = [m for lst in com_problema["inconsistencias"] for m in lst]
    tipo_mais_comum = pd.Series(todos_motivos).mode().iat[0] if todos_motivos else "—"
    n_tipo_mais_comum = sum(1 for m in todos_motivos if m == tipo_mais_comum) if todos_motivos else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Linhas com inconsistência", f"{n_problema} de {n_total}", help=f"{formatar_pct(pct_problema)} das linhas filtradas")
    c2.metric("Valor sob suspeita", formatar_moeda(valor_suspeito), help="Soma do valor da parcela nas linhas sinalizadas")
    c3.metric("Tipo mais comum", tipo_mais_comum if len(tipo_mais_comum) < 40 else tipo_mais_comum[:37] + "…",
              help=f"{n_tipo_mais_comum} ocorrência(s)" if todos_motivos else None)

    st.divider()

    if com_problema.empty:
        st.success("Nenhuma inconsistência encontrada nos campos cruzados para os filtros atuais.")
    else:
        tabela_incons = com_problema[["cliente", "teatro", "status", "valor_parcela", "inconsistencias"]].copy()
        tabela_incons["valor_parcela"] = tabela_incons["valor_parcela"].map(formatar_moeda)
        tabela_incons["inconsistencias"] = tabela_incons["inconsistencias"].map(lambda lst: " · ".join(lst))
        tabela_incons = tabela_incons.sort_values("valor_parcela", ascending=False)
        tabela_incons.columns = ["Cliente", "Teatro", "Status", "Valor da Parcela", "Motivo(s) da Inconsistência"]
        st.dataframe(tabela_incons, hide_index=True, use_container_width=True, height=420)

# =============================================================================
# ABA 4 — INSIGHTS & PROJEÇÕES
# =============================================================================
with tab_insights:
    st.subheader("Insights & Projeções")
    st.caption("Leitura automática dos números acima — recalculada a cada filtro.")

    realizados_base = f.loc[f["status_grupo"] == "Realizado"]
    total_realizado_base = realizados_base["valor_parcela"].sum()

    col1, col2 = st.columns(2)

    # 1. Concentração de clientes
    with col1:
        st.markdown("**Concentração de clientes**")
        por_cliente_base = realizados_base.groupby("cliente")["valor_parcela"].sum().sort_values(ascending=False)
        if por_cliente_base.empty:
            st.markdown("### —")
            st.write("Sem faturamento realizado no período para calcular concentração.")
        else:
            top3 = por_cliente_base.head(3)
            pct_top3 = (top3.sum() / total_realizado_base) if total_realizado_base > 0 else 0.0
            # Nomes completos, sem truncar: nomes de clientes muitas vezes só se
            # diferenciam no final (ex.: "... - SALA 1" vs "... - SALA 1 E SALA 2"),
            # e um corte fixo pode fazer dois clientes distintos parecerem iguais.
            nomes_top3 = ", ".join(titulo_caso(c) for c in top3.index)
            st.markdown(f"### {formatar_pct(pct_top3)}")
            st.write(
                f"Os 3 maiores clientes ({nomes_top3}) respondem por essa fatia do faturamento realizado. "
                + ("Concentração alta — a perda de um desses clientes teria impacto material."
                   if pct_top3 > 0.4 else "Concentração sob controle.")
            )

    # 2. Desempenho por teatro (melhor/pior vs. meta)
    with col2:
        st.markdown("**Desempenho por teatro**")
        realizado_por_teatro_base = realizados_base.groupby("teatro")["valor_parcela"].sum()
        com_meta = metas.loc[metas["meta"] > 0].copy()
        com_meta["realizado"] = com_meta["teatro"].map(realizado_por_teatro_base).fillna(0.0)
        com_meta["pct"] = com_meta["realizado"] / com_meta["meta"]
        if com_meta.empty:
            st.markdown("### —")
            st.write("Sem metas cadastradas para calcular desempenho.")
        else:
            melhor = com_meta.loc[com_meta["pct"].idxmax()]
            pior = com_meta.loc[com_meta["pct"].idxmin()]
            st.markdown(f"### {titulo_caso(melhor['teatro'])}")
            st.write(
                f"É o espaço mais próximo (ou acima) da meta, com {formatar_pct(melhor['pct'])} de atingimento. "
                f"No outro extremo, {titulo_caso(pior['teatro'])} está em {formatar_pct(pior['pct'])} — "
                f"candidato a atenção comercial prioritária."
            )

    col3, col4 = st.columns(2)

    # 3. Sazonalidade
    with col3:
        st.markdown("**Sazonalidade**")
        por_mes_real = (
            realizados_base.dropna(subset=["pago_em"])
            .assign(mes=lambda d: d["pago_em"].map(lambda x: f"{x.year}-{x.month:02d}"))
            .groupby("mes")["valor_parcela"].sum()
        )
        abertos_base = f.loc[f["status_grupo"] == "Em aberto"]
        por_mes_proj = (
            abertos_base.dropna(subset=["previsao_pagamento"])
            .assign(mes=lambda d: d["previsao_pagamento"].map(lambda x: f"{x.year}-{x.month:02d}"))
            .groupby("mes")["saldo_em_aberto"].sum()
        )
        pico_real = por_mes_real.idxmax() if not por_mes_real.empty else None
        pico_proj = por_mes_proj.idxmax() if not por_mes_proj.empty else None
        if pico_real or pico_proj:
            st.markdown(f"### {rotulo_mes(pico_real) if pico_real else '—'}")
            texto = ""
            if pico_real:
                texto += f"Foi o mês de maior receita realizada até agora ({formatar_moeda(por_mes_real[pico_real])}). "
            if pico_proj:
                texto += (f"O maior volume projetado está em {rotulo_mes(pico_proj)} "
                          f"({formatar_moeda(por_mes_proj[pico_proj])}), o que merece atenção de cobrança "
                          f"à medida que a data se aproxima.")
            st.write(texto_seguro(texto))
        else:
            st.markdown("### —")
            st.write("Sem dados suficientes para avaliar sazonalidade.")

    # 4. Inadimplência sobre o saldo em aberto
    with col4:
        st.markdown("**Inadimplência sobre o saldo em aberto**")
        abertos_periodo = f_periodo.loc[f_periodo["status_grupo"] == "Em aberto"]
        soma_aberto = abertos_periodo["saldo_em_aberto"].sum()
        soma_vencido = abertos_periodo.loc[abertos_periodo["em_atraso_calculado"], "saldo_em_aberto"].sum()
        taxa_inad = (soma_vencido / soma_aberto) if soma_aberto > 0 else 0.0
        st.markdown(f"### {formatar_pct(taxa_inad)}")
        st.write(texto_seguro(
            f"{formatar_moeda(soma_vencido)} de {formatar_moeda(soma_aberto)} em aberto já está com a "
            f"previsão de pagamento vencida." if soma_aberto > 0 else
            "Sem saldo em aberto no período para medir inadimplência."
        ))

    st.divider()

    col5, col6 = st.columns(2)

    # 5. Qualidade dos dados
    with col5:
        st.markdown("**Qualidade dos dados**")
        com_issue_base = f.loc[~f["consistente"]]
        pct_issue = (com_issue_base.shape[0] / f.shape[0]) if f.shape[0] > 0 else 0.0
        st.markdown(f"### {formatar_pct(pct_issue) if pct_issue > 0 else 'OK'}")
        if not com_issue_base.empty:
            st.write(texto_seguro(
                f"{com_issue_base.shape[0]} de {f.shape[0]} linha(s) têm algum campo contraditório "
                f"(ver aba Consistência de Dados) — some {formatar_moeda(com_issue_base['valor_parcela'].sum())} "
                f"em valor sob suspeita."
            ))
        else:
            st.write("Nenhuma inconsistência encontrada nos campos cruzados para os filtros atuais.")

    # 6. Repasse a fornecedores
    with col6:
        st.markdown("**Repasse a fornecedores**")
        sem_cancelado = f.loc[f["status_grupo"] != "Cancelado"]
        soma_repasse = sem_cancelado["valor_repasse"].sum()
        soma_base_parcelas = sem_cancelado["valor_parcela"].sum()
        pct_repasse = (soma_repasse / soma_base_parcelas) if soma_base_parcelas > 0 else 0.0
        st.markdown(f"### {texto_seguro(formatar_moeda(soma_repasse))}")
        st.write(
            f"Equivale a {formatar_pct(pct_repasse)} do valor total das parcelas (realizado + em aberto) "
            f"no período — receita que passa pelo caixa mas não fica com a operação."
        )

    st.caption(
        "Fonte: aba 'EVENTOS CORP' (base operacional) e aba 'RESUMO' (metas por Teatro/Espaço). "
        "A classificação de cada linha (Realizado / Em aberto / Cancelado) segue **exclusivamente** "
        "a coluna STATUS; o valor considerado é o da coluna 'Saldo Pago' (valor da parcela, incluindo "
        "repasse quando houver) — linhas onde os campos não batem entre si aparecem na aba "
        "**Consistência de Dados** em vez de serem corrigidas silenciosamente."
    )
