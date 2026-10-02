"""Previsão de quando o edital deve sair, para os concursos que ainda não têm data.

Duas fontes de evidência, nesta ordem de prioridade:

1. **Fase do processo.** Se já há comissão formada, banca contratada ou edital
   publicado, isso vale mais do que qualquer média histórica: o processo está andando
   e o prazo passa a ser medido em meses.

2. **Ciclo histórico do órgão.** Sem nada andando, a melhor estimativa é o intervalo
   médio entre os editais anteriores daquele mesmo órgão, somado à data do último.
   Quando o órgão só tem um edital registrado, usa-se o ciclo típico da esfera
   (municipal, estadual, federal), e a confiança cai.

Um órgão cujo ciclo já venceu é o caso mais interessante do radar: ele não está
"sem data", está atrasado — e atraso acumulado é o que costuma preceder uma
autorização.
"""

from __future__ import annotations

import statistics
from datetime import date

# Quanto tempo costuma separar a fase atual da publicação do edital, em meses:
# (mínimo, central, máximo).
HORIZONTE_FASE: dict[str, tuple[int, int, int]] = {
    "aberto": (0, 0, 0),
    "iminente": (0, 1, 3),
    "autorizado": (3, 7, 14),
}

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
         "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _ano_decimal(texto: str) -> float:
    """Aceita '2019' ou '2019-06' e devolve o ano como número."""
    partes = str(texto).split("-")
    ano = float(partes[0])
    if len(partes) > 1:
        ano += (int(partes[1]) - 1) / 12
    return ano


def _rotular(ano_decimal: float) -> str:
    ano = int(ano_decimal)
    mes = min(11, max(0, int(round((ano_decimal - ano) * 12))))
    if mes >= 12:
        ano, mes = ano + 1, 0
    return f"{MESES[mes]} de {ano}"


def _semestre(ano_decimal: float) -> str:
    ano = int(ano_decimal)
    return f"{'1º' if (ano_decimal - ano) < 0.5 else '2º'} semestre de {ano}"


def _hoje_decimal() -> float:
    h = date.today()
    return h.year + (h.month - 1) / 12


def prever(concurso: dict, ciclos_padrao: dict[str, float]) -> dict | None:
    """Devolve a previsão de publicação do edital, ou None quando não dá para estimar."""
    status = concurso.get("status", "previsto")
    if status in ("encerrado", "andamento"):
        return None

    hoje = _hoje_decimal()
    historico = sorted(_ano_decimal(h) for h in concurso.get("historico", []))
    ultimo = historico[-1] if historico else None

    # --- ciclo do órgão -------------------------------------------------
    ciclo = desvio = None
    n_ciclos = 0
    origem_ciclo = ""
    if len(historico) >= 2:
        intervalos = [b - a for a, b in zip(historico, historico[1:])]
        n_ciclos = len(intervalos)
        ciclo = statistics.fmean(intervalos)
        desvio = statistics.stdev(intervalos) if n_ciclos >= 2 else max(ciclo * 0.25, 1.0)
        origem_ciclo = f"{n_ciclos} ciclo{'s' if n_ciclos > 1 else ''} do próprio órgão"
    elif historico:
        ciclo = ciclos_padrao.get(concurso.get("esfera", "municipal"), 9.0)
        desvio = ciclo * 0.35
        origem_ciclo = f"ciclo típico da esfera {concurso.get('esfera', 'municipal')}"

    atraso = round(hoje - (ultimo + ciclo), 1) if (ultimo is not None and ciclo) else None

    # --- caminho 1: o próprio órgão anunciou uma janela -----------------
    declarada = concurso.get("janela_declarada")
    if declarada and status not in ("aberto", "iminente"):
        alvo = _ano_decimal(declarada)
        inicio, fim = max(alvo, hoje), alvo + 1.0
        central = (inicio + fim) / 2
        texto = (f"O próprio órgão declarou intenção de publicar em {declarada}. "
                 f"O ciclo histórico apontaria para {_semestre(ultimo + ciclo)}"
                 if (ultimo is not None and ciclo) else
                 f"O próprio órgão declarou intenção de publicar em {declarada}")
        if ultimo is not None and ciclo:
            texto += (", então a declaração antecipa a média." if alvo < ultimo + ciclo
                      else ", em linha com a média.")
        else:
            texto += "."
        return {
            "metodo": "janela declarada pelo órgão",
            "inicio": round(inicio, 2), "central": round(central, 2), "fim": round(fim, 2),
            "rotulo": f"ao longo de {declarada}",
            "confianca": "média",
            "ciclo_medio_anos": round(ciclo, 1) if ciclo else None,
            "desvio_anos": round(desvio, 1) if desvio else None,
            "ciclos_observados": n_ciclos,
            "ultimo_edital": int(ultimo) if ultimo else None,
            "atraso_anos": atraso,
            "base": f"anúncio do órgão" + (f", conferido contra {origem_ciclo}" if origem_ciclo else ""),
            "texto": texto,
        }

    # --- caminho 2: o processo já está andando --------------------------
    if status in HORIZONTE_FASE:
        lo, meio, hi = HORIZONTE_FASE[status]
        inicio, central, fim = hoje + lo / 12, hoje + meio / 12, hoje + hi / 12
        if status == "aberto":
            texto = "Edital já publicado."
        elif status == "iminente":
            texto = f"Edital deve sair até {_rotular(fim)} — banca já contratada ou edital na praça."
        else:
            texto = f"Edital provável no {_semestre(central)}, entre {_rotular(inicio)} e {_rotular(fim)}."
            if atraso is not None and atraso > 0:
                texto += f" O órgão está {atraso:.0f} ano{'s' if atraso >= 2 else ''} além do próprio ciclo, o que empurra para o começo da janela."
        return {
            "metodo": "fase do processo",
            "inicio": round(inicio, 2), "central": round(central, 2), "fim": round(fim, 2),
            "rotulo": _semestre(central) if status == "autorizado" else _rotular(fim),
            "confianca": "alta" if status in ("aberto", "iminente") else "média",
            "ciclo_medio_anos": round(ciclo, 1) if ciclo else None,
            "desvio_anos": round(desvio, 1) if desvio else None,
            "ciclos_observados": n_ciclos,
            "ultimo_edital": int(ultimo) if ultimo else None,
            "atraso_anos": atraso,
            "base": origem_ciclo or "fase declarada do processo",
            "texto": texto,
        }

    # --- caminho 3: só o ciclo histórico --------------------------------
    if ciclo is None or ultimo is None:
        return {
            "metodo": "sem base",
            "inicio": None, "central": None, "fim": None,
            "rotulo": "sem histórico para estimar",
            "confianca": "nenhuma",
            "ciclo_medio_anos": None, "desvio_anos": None, "ciclos_observados": 0,
            "ultimo_edital": None, "atraso_anos": None,
            "base": "nenhum edital anterior registrado",
            "texto": "Não há edital anterior registrado para calcular o ciclo deste órgão.",
        }

    central = ultimo + ciclo
    inicio, fim = central - desvio, central + desvio

    if central <= hoje:
        # Ciclo vencido: a janela passa a correr a partir de hoje.
        inicio, central, fim = hoje, hoje + 0.75, hoje + 2.0
        texto = (f"Ciclo vencido. O último edital foi em {int(ultimo)} e o órgão costuma repetir "
                 f"a cada {ciclo:.0f} anos, ou seja, já está {atraso:.0f} ano"
                 f"{'s' if atraso >= 2 else ''} atrasado. Pode sair a qualquer momento — "
                 f"o mais provável é até {_rotular(fim)}.")
        confianca = "média" if n_ciclos >= 2 else "baixa"
    else:
        texto = (f"Previsto para o {_semestre(central)}. Último edital em {int(ultimo)} e ciclo de "
                 f"{ciclo:.0f} anos ({origem_ciclo}); a margem vai de {_rotular(inicio)} a {_rotular(fim)}.")
        confianca = "média" if n_ciclos >= 2 else "baixa"

    return {
        "metodo": "ciclo histórico",
        "inicio": round(inicio, 2), "central": round(central, 2), "fim": round(fim, 2),
        "rotulo": "a qualquer momento" if atraso and atraso > 0 else _semestre(central),
        "confianca": confianca,
        "ciclo_medio_anos": round(ciclo, 1),
        "desvio_anos": round(desvio, 1),
        "ciclos_observados": n_ciclos,
        "ultimo_edital": int(ultimo),
        "atraso_anos": atraso,
        "base": origem_ciclo,
        "texto": texto,
    }


def bonus_atraso(previsao: dict | None, teto: float) -> float:
    """Ciclo vencido antecipa o edital: vale pontos no critério de janela.

    Cresce até metade do teto do critério, saturando em 5 anos de atraso.
    """
    if not previsao or not previsao.get("atraso_anos"):
        return 0.0
    atraso = previsao["atraso_anos"]
    if atraso <= 0:
        return 0.0
    return round(min(atraso / 5.0, 1.0) * (teto * 0.5), 1)
