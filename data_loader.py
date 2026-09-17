"""
ETL — leitura, limpeza e tratamento dos dados do Google Sheets.

Responsabilidades deste módulo:
1. Buscar o CSV público de cada aba (EVENTOS CORP, RESUMO).
2. Tratar tipos: datas (DD/MM/AAAA), moeda (R$ 1.234,56 -> float), texto.
3. Normalizar status e sinalizar inconsistências.
4. Calcular colunas derivadas (saldo em aberto, atraso, parcela atual/total).

Este módulo é 100% independente do Streamlit — pode ser testado isoladamente
com `python data_loader.py` (usa arquivos CSV locais de teste, se existirem,
como fallback quando não há rede).
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
import requests

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("etl")


# ---------------------------------------------------------------------------
# Exceções específicas — permitem que a UI diferencie "sem rede" de
# "estrutura da planilha mudou", que exigem mensagens/ações diferentes.
# ---------------------------------------------------------------------------

class FonteDadosError(Exception):
    """Erro ao buscar o CSV da planilha (rede, permissão, planilha movida)."""


class EstruturaInvalidaError(Exception):
    """O CSV foi baixado, mas a estrutura de colunas não é a esperada."""


# ---------------------------------------------------------------------------
# Helpers de parsing (formato brasileiro)
# ---------------------------------------------------------------------------

def parse_moeda_brl(valor: object) -> float:
    """
    Converte string de moeda brasileira em float.
    Aceita: "R$  20.925,00", "1.200.000", "0,00", "", None, "-", NaN.
    Regra: se houver vírgula, ela é o separador decimal e pontos são
    separadores de milhar. Se não houver vírgula, pontos são separadores
    de milhar (ex.: Meta "1.200.000" -> 1200000.0).
    """
    if valor is None:
        return 0.0
    s = str(valor).strip()
    s = s.replace("R$", "").strip()
    s = re.sub(r"\s+", "", s)
    if s in ("", "-", "nan", "NaN", "None"):
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        logger.warning("Valor monetário não reconhecido, tratado como 0: %r", valor)
        return 0.0


def parse_percentual(valor: object) -> float:
    """Converte '75%' -> 0.75. Retorna 0.0 se vazio/inválido."""
    if valor is None:
        return 0.0
    s = str(valor).strip().replace("%", "").replace(",", ".")
    if s in ("", "-", "nan"):
        return 0.0
    try:
        return float(s) / 100.0
    except ValueError:
        return 0.0


def parse_data_br(valor: object) -> date | None:
    """
    Converte 'DD/MM/AAAA' -> date. Células com múltiplas datas (eventos de
    vários dias, ex. "07/07/2026\n24/10/2026") retornam a PRIMEIRA data —
    suficiente para ordenação temporal; o texto original fica preservado
    em colunas *_raw para exibição.
    """
    if valor is None:
        return None
    s = str(valor).strip()
    if s in ("", "nan", "None"):
        return None
    primeira = re.split(r"[\n,;]| a | e ", s)[0].strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(primeira, fmt).date()
        except ValueError:
            continue
    logger.warning("Data não reconhecida: %r", valor)
    return None


def parse_parcela(valor: object) -> tuple[int | None, int | None]:
    """'2/3' -> (2, 3). Retorna (None, None) se vazio/inválido."""
    s = str(valor).strip()
    m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", s)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def normalizar_texto(valor: object) -> str:
    if valor is None:
        return ""
    return str(valor).strip()


def normalizar_sim_nao(valor: object) -> bool:
    return normalizar_texto(valor).upper().startswith("SIM")


# ---------------------------------------------------------------------------
# Download do CSV
# ---------------------------------------------------------------------------

def _baixar_csv(sheet_name: str, timeout: int = 20) -> str:
    url = config.GVIZ_URL_TEMPLATE.format(
        spreadsheet_id=config.SPREADSHEET_ID,
        sheet_name=requests.utils.quote(sheet_name),
    )
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise FonteDadosError(
            f"Não foi possível baixar a aba '{sheet_name}'. Verifique: "
            f"(1) o compartilhamento da planilha está como 'Qualquer pessoa "
            f"com o link pode visualizar'? (2) o SPREADSHEET_ID em config.py "
            f"está correto? Erro original: {exc}"
        ) from exc

    texto = resp.content.decode("utf-8-sig", errors="replace")
    # O endpoint gviz devolve uma página de login/erro (HTML) quando a
    # planilha não está acessível publicamente — detectamos isso aqui em
    # vez de deixar o pandas falhar com um erro confuso mais adiante.
    if texto.lstrip().startswith("<"):
        raise FonteDadosError(
            f"A aba '{sheet_name}' retornou HTML em vez de CSV — geralmente "
            f"significa que a planilha NÃO está compartilhada como "
            f"'Qualquer pessoa com o link pode visualizar'. Ajuste o "
            f"compartilhamento no Google Sheets e tente novamente."
        )
    return texto


def _ler_csv_teste_ou_remoto(sheet_name: str, caminho_teste: str | None) -> pd.DataFrame:
    """Usa um CSV local (fixtures de teste) se fornecido; senão baixa da web."""
    if caminho_teste:
        with open(caminho_teste, encoding="utf-8-sig") as f:
            texto = f.read()
    else:
        texto = _baixar_csv(sheet_name)
    return pd.read_csv(io.StringIO(texto), header=None, dtype=str, keep_default_na=False)


# ---------------------------------------------------------------------------
# EVENTOS CORP
# ---------------------------------------------------------------------------

def carregar_eventos_corp(caminho_teste: str | None = None) -> pd.DataFrame:
    raw = _ler_csv_teste_ou_remoto(config.SHEET_EVENTOS, caminho_teste)

    if raw.shape[1] < config.EVENTOS_MIN_COLS:
        raise EstruturaInvalidaError(
            f"A aba '{config.SHEET_EVENTOS}' tem {raw.shape[1]} colunas, "
            f"esperado no mínimo {config.EVENTOS_MIN_COLS}. A estrutura da "
            f"planilha mudou — revise os índices COL_* em config.py antes "
            f"de confiar nos números deste dashboard."
        )

    df = raw.iloc[config.EVENTOS_HEADER_ROWS:].reset_index(drop=True)

    out = pd.DataFrame({
        "mes_ano": df[config.COL_MES_ANO].map(normalizar_texto),
        "teatro": df[config.COL_TEATRO].map(normalizar_texto).str.upper(),
        "data_evento_raw": df[config.COL_DATA_EVENTO].map(normalizar_texto),
        "cliente": df[config.COL_CLIENTE].map(normalizar_texto),
        "previsao_pagamento": df[config.COL_PREVISAO_PAGAMENTO].map(parse_data_br),
        "valor_previsto": df[config.COL_VALOR_PREVISTO].map(parse_moeda_brl),
        "havera_repasse": df[config.COL_HAVERA_REPASSE].map(normalizar_sim_nao),
        "valor_repasse": df[config.COL_VALOR_REPASSE].map(parse_moeda_brl),
        "status": df[config.COL_STATUS].map(normalizar_texto).str.upper(),
        "pago_em": df[config.COL_PAGO_EM].map(parse_data_br),
        "parcela_raw": df[config.COL_PARCELA].map(normalizar_texto),
        "saldo_pago": df[config.COL_SALDO_PAGO].map(parse_moeda_brl),
        "inserido_sistema": df[config.COL_INSERIDO_SISTEMA].map(normalizar_sim_nao),
        "inserido_fluxo_caixa": df[config.COL_INSERIDO_FLUXO_CAIXA].map(normalizar_sim_nao),
        # OBS é opcional (ver EVENTOS_MIN_COLS em config.py) — algumas cargas
        # da planilha não trazem essa coluna quando ela está vazia.
        "obs": df[config.COL_OBS].map(normalizar_texto) if config.COL_OBS in df.columns else "",
    })

    # Remove linhas 100% vazias (linhas em branco no fim da planilha)
    campos_chave = ["teatro", "cliente", "status"]
    out = out[~(out[campos_chave].apply(lambda col: col == "", axis=0).all(axis=1))].copy()
    out = out[out["cliente"] != ""].reset_index(drop=True)

    # Parcela atual/total
    parcelas = out["parcela_raw"].map(parse_parcela)
    out["parcela_atual"] = parcelas.map(lambda p: p[0])
    out["parcela_total"] = parcelas.map(lambda p: p[1])

    # Status fora do vocabulário conhecido: preserva o valor mas sinaliza,
    # em vez de silenciosamente excluir da análise.
    desconhecidos = sorted(set(out["status"]) - set(config.STATUS_CANONICOS) - {""})
    if desconhecidos:
        logger.warning(
            "Status não mapeado(s) encontrado(s) na planilha: %s. "
            "Essas linhas serão tratadas como 'em aberto' por padrão — "
            "valide com a equipe de operações e atualize config.py.",
            desconhecidos,
        )

    out["status_grupo"] = out["status"].map(_classificar_status_grupo)

    # ---------------------------------------------------------------------
    # REGRA DE GOVERNANÇA (decisão do usuário, 17/09/2026): STATUS é a ÚNICA
    # autoridade que decide se uma linha é Realizado, Em aberto ou Cancelado.
    # Nenhum outro campo (data, "Saldo Pago", etc.) pode reclassificar uma
    # linha — eles só alimentam o VALOR da parcela ou disparam um alerta de
    # inconsistência (ver detectar_inconsistencias, abaixo). Isso está
    # implementado de forma idêntica no dashboard HTML (Artifact) publicado
    # em paralelo a este app — ambos usam a mesma regra.
    #
    # "valor_parcela" é o valor total da parcela, recebido ou a receber,
    # dependendo só do STATUS: usa "Saldo Pago" quando preenchido (>0),
    # senão cai para Valor Previsto + Valor Repasse como estimativa. Esse
    # valor NUNCA é subtraído de outro — achado de qualidade de dados
    # validado contra a planilha real em 17/09/2026: a coluna "Saldo Pago"
    # vem preenchida com o valor total da parcela mesmo em linhas cujo
    # status ainda não é PAGO (não distingue "recebido" de "a receber").
    # ---------------------------------------------------------------------
    out["valor_parcela"] = out["saldo_pago"].where(
        out["saldo_pago"] > 0, out["valor_previsto"] + out["valor_repasse"]
    )

    out["saldo_em_aberto"] = 0.0
    out.loc[out["status_grupo"] == "Em aberto", "saldo_em_aberto"] = out.loc[
        out["status_grupo"] == "Em aberto", "valor_parcela"
    ]

    # Data de referência para os filtros de período: usa "Pago em" quando
    # existe (receita já realizada) e cai para "Previsão de Pagamento" nos
    # demais casos (receita futura/pendente). Essa é a coluna que os
    # filtros de período (sidebar) usam.
    out["data_referencia"] = out["pago_em"].combine_first(out["previsao_pagamento"])

    hoje = date.today()
    vencido_por_data = (
        (out["status"] != config.STATUS_PAGO)
        & (out["status"] != config.STATUS_CANCELADO)
        & out["previsao_pagamento"].notna()
        & (out["previsao_pagamento"] < hoje)
    )
    # "Vencido" = a previsão de pagamento já passou OU a equipe já marcou o
    # status como EM ATRASO manualmente (mesmo que a previsão registrada
    # ainda não tenha vencido — nesse caso o status manual prevalece, para
    # não mostrar um contrato como "Em atraso" no status e "A vencer" na
    # situação ao mesmo tempo).
    out["em_atraso_calculado"] = vencido_por_data | (out["status"] == config.STATUS_ATRASADO)

    inconsistencias = out.apply(lambda r: _detectar_inconsistencias(r, hoje), axis=1)
    out["inconsistencias"] = inconsistencias
    out["consistente"] = inconsistencias.map(lambda lst: len(lst) == 0)

    return out


# ---------------------------------------------------------------------------
# Detecção de inconsistências — NUNCA corrige silenciosamente, só sinaliza.
# Espelha, regra a regra, a lógica implementada no dashboard HTML (Artifact)
# publicado em paralelo, para os dois deliverables lerem os dados da mesma
# forma. Uma linha pode acumular mais de um motivo.
# ---------------------------------------------------------------------------

def _detectar_inconsistencias(r: pd.Series, hoje: date) -> list[str]:
    motivos: list[str] = []

    soma_teatro_repasse = (r["valor_previsto"] or 0.0) + (r["valor_repasse"] or 0.0)

    # 1. "Saldo Pago" preenchido mas não bate com Valor do Teatro + Repasse.
    if r["saldo_pago"] > 0 and abs(r["saldo_pago"] - soma_teatro_repasse) > 0.01:
        motivos.append(
            f"Saldo Pago ({formatar_moeda_simples(r['saldo_pago'])}) não bate com "
            f"Valor do Teatro + Repasse ({formatar_moeda_simples(soma_teatro_repasse)})"
        )

    # 2. Nenhum valor disponível (nem Saldo Pago, nem Previsto+Repasse).
    if r["valor_parcela"] is None or r["valor_parcela"] <= 0:
        motivos.append("Nenhum valor de parcela identificado (Saldo Pago e Valor Previsto + Repasse ambos vazios/zero)")

    # 3. Status PAGO sem data em "Pago em".
    if r["status"] == config.STATUS_PAGO and r["pago_em"] is None:
        motivos.append('Status PAGO sem data em "Pago em"')

    # 4. Data em "Pago em" preenchida mas status não é PAGO.
    if r["pago_em"] is not None and r["status"] != config.STATUS_PAGO:
        motivos.append(f'"Pago em" preenchido mas status é {r["status"] or "(vazio)"}, não PAGO')

    # 5. Status EM ATRASO mas a previsão de pagamento ainda não venceu.
    if r["status"] == config.STATUS_ATRASADO and r["previsao_pagamento"] is not None and r["previsao_pagamento"] >= hoje:
        motivos.append("Status EM ATRASO mas a previsão de pagamento não está vencida")

    # 6. Número de parcela inválido (ausente, ou parcela atual > total, ou <= 0).
    pa, pt = r["parcela_atual"], r["parcela_total"]
    if pa is None or pt is None or pa <= 0 or pt <= 0 or pa > pt:
        motivos.append(f'Número de parcela inválido ("{r["parcela_raw"]}")')

    # 7. Diz que haverá repasse, mas o valor do repasse é zero/vazio.
    if r["havera_repasse"] and (r["valor_repasse"] or 0.0) <= 0:
        motivos.append('"Haverá Repasse ao Fornecedor?" = SIM mas Valor do Repasse é zero')

    # 8. Diz que NÃO haverá repasse, mas o valor do repasse é maior que zero.
    if not r["havera_repasse"] and (r["valor_repasse"] or 0.0) > 0:
        motivos.append('"Haverá Repasse ao Fornecedor?" = NÃO mas Valor do Repasse é maior que zero')

    # 9. Status fora do vocabulário canônico conhecido.
    if r["status"] not in config.STATUS_CANONICOS:
        motivos.append(f'Status "{r["status"]}" fora do vocabulário conhecido ({", ".join(config.STATUS_CANONICOS)})')

    return motivos


def formatar_moeda_simples(v: float) -> str:
    """Formatação compacta de moeda BRL para uso dentro das mensagens de inconsistência."""
    return f"R$ {v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _classificar_status_grupo(status: str) -> str:
    if status in config.STATUS_QUE_CONTAM_COMO_RECEITA_REALIZADA:
        return "Realizado"
    if status == config.STATUS_CANCELADO:
        return "Cancelado"
    # Inclui EM ATRASO, AGUARDANDO PAGAMENTO, EVENTO NOVO e qualquer status
    # desconhecido (fail-safe: melhor contar como pendência a investigar do
    # que sumir da análise silenciosamente).
    return "Em aberto"


# ---------------------------------------------------------------------------
# RESUMO (metas por teatro)
# ---------------------------------------------------------------------------

def carregar_metas(caminho_teste: str | None = None) -> pd.DataFrame:
    raw = _ler_csv_teste_ou_remoto(config.SHEET_RESUMO, caminho_teste)
    df = raw.iloc[config.RESUMO_HEADER_ROWS:].reset_index(drop=True)

    registros = []
    for _, row in df.iterrows():
        espaco = normalizar_texto(row[config.RESUMO_COL_ESPACO])
        if espaco == "" or espaco.lower() == config.RESUMO_STOP_LABEL:
            break  # chegou na linha "Valor Total" -> fim da tabela de teatros
        registros.append({
            "teatro": espaco.upper(),
            "meta": parse_moeda_brl(row[config.RESUMO_COL_META]),
        })

    if not registros:
        raise EstruturaInvalidaError(
            f"Não foi possível localizar nenhuma linha de Teatro/Espaço na "
            f"aba '{config.SHEET_RESUMO}'. A estrutura da planilha pode ter "
            f"mudado — revise RESUMO_COL_* em config.py."
        )

    return pd.DataFrame(registros)


# ---------------------------------------------------------------------------
# Carga completa
# ---------------------------------------------------------------------------

@dataclass
class BaseDados:
    eventos: pd.DataFrame
    metas: pd.DataFrame
    carregado_em: datetime


def carregar_tudo(
    caminho_teste_eventos: str | None = None,
    caminho_teste_resumo: str | None = None,
) -> BaseDados:
    eventos = carregar_eventos_corp(caminho_teste_eventos)
    metas = carregar_metas(caminho_teste_resumo)
    return BaseDados(eventos=eventos, metas=metas, carregado_em=datetime.now())


if __name__ == "__main__":
    # Teste rápido local: `python data_loader.py <csv_eventos> <csv_resumo>`
    import sys

    ce = sys.argv[1] if len(sys.argv) > 1 else None
    cr = sys.argv[2] if len(sys.argv) > 2 else None
    base = carregar_tudo(ce, cr)
    print("=== EVENTOS CORP (tratado) ===")
    print(base.eventos.to_string())
    print("\n=== METAS (RESUMO, tratado) ===")
    print(base.metas.to_string())
    print("\nRealizado total:", base.eventos.loc[base.eventos.status_grupo == "Realizado", "valor_parcela"].sum())
    print("Em aberto total:", base.eventos.loc[base.eventos.status_grupo == "Em aberto", "saldo_em_aberto"].sum())
    print("Linhas inconsistentes:", (~base.eventos.consistente).sum(), "de", len(base.eventos))
