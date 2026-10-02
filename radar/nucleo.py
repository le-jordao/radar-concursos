"""Carregamento de dados, pontuação de aderência, matriz de conteúdo e plano de estudo."""

from __future__ import annotations

import json
import unicodedata
from datetime import date, datetime
from pathlib import Path

from . import previsao as _previsao

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"


# ---------------------------------------------------------------- utilidades


def sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _ler(nome: str) -> dict:
    with open(DADOS / nome, encoding="utf-8") as fh:
        return json.load(fh)


def carregar() -> dict:
    """Lê as quatro bases de dados do disco."""
    return {
        "perfil": _ler("perfil.json"),
        "municipios": _ler("municipios.json"),
        "disciplinas": _ler("disciplinas.json"),
        "concursos": _ler("concursos.json"),
    }


def salvar_concursos(base: dict) -> None:
    base["atualizado_em"] = date.today().isoformat()
    with open(DADOS / "concursos.json", "w", encoding="utf-8") as fh:
        json.dump(base, fh, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- pontuação

PESO_STATUS = {
    "aberto": 10.0,
    "iminente": 9.0,
    "autorizado": 7.0,
    "previsto": 5.0,
    "andamento": 2.0,
    "encerrado": 0.0,
}

ACIONAVEL = {"aberto", "iminente", "autorizado", "previsto"}

ROTULO_ACAO = {
    "aberto": "INSCREVER",
    "iminente": "PREPARAR",
    "autorizado": "PREPARAR",
    "previsto": "MONITORAR",
    "andamento": "REFERÊNCIA",
    "encerrado": "REFERÊNCIA",
}


def distancia(municipios: dict, local: str) -> float | None:
    tabela = municipios["distancias_km"]
    alvo = sem_acento(local)
    for chave, km in tabela.items():
        if sem_acento(chave) == alvo:
            return float(km)
    return None


PESOS_PADRAO = {"aderencia": 35, "proximidade": 25, "chance": 20, "retorno": 10, "janela": 10}


def pesos(perfil: dict) -> dict[str, float]:
    """Quanto cada critério vale. Configurável em perfil.json."""
    cfg = perfil.get("pesos", {})
    return {k: float(cfg.get(k, v)) for k, v in PESOS_PADRAO.items()}


def _pontos_aderencia(concurso: dict, perfil: dict) -> tuple[float, str]:
    teto = pesos(perfil)["aderencia"]
    cargo = sem_acento(concurso.get("cargo", ""))

    for excluido in perfil["exclusoes"]:
        if sem_acento(excluido) in cargo:
            return 0.0, f"cargo contém '{excluido}' (lista de exclusões do perfil)"

    trilha_id = concurso.get("trilha")
    if not trilha_id:
        return 0.0, "nenhuma trilha do seu perfil se aplica a este cargo"

    trilha = next((t for t in perfil["trilhas"] if t["id"] == trilha_id), None)
    if trilha is None:
        return 0.0, "trilha desconhecida"

    pontos = teto * trilha["peso"]
    motivo = trilha["nome"]

    # Bônus quando o cargo é exatamente a formação do candidato.
    if "engenheiro civil" in cargo or "engenharia civil" in cargo:
        pontos = min(teto, pontos + teto * 0.086)
        motivo += " — cargo casa exatamente com a sua formação"

    return round(pontos, 1), motivo


def _pontos_proximidade(concurso: dict, perfil: dict, municipios: dict) -> tuple[float, float | None]:
    teto = pesos(perfil)["proximidade"]
    km_prova = distancia(municipios, concurso.get("local_prova", ""))

    # Órgão com unidade perto de casa (INSS, Correios, bancos, Detran): o que pesa é a
    # lotação possível, não a cidade da prova. A prova é um dia; a lotação é todo dia.
    if concurso.get("lotacao_escolhivel") and concurso.get("lotacao_km") is not None:
        km = float(concurso["lotacao_km"])
    else:
        km = km_prova

    if km is None:
        return teto * 0.4, None

    conf = perfil["base"]["raio_confortavel_km"]
    maxi = perfil["base"]["raio_maximo_km"]

    # Dentro do raio confortável a perda é pequena; depois dele cai rápido até zerar.
    if km <= conf:
        pontos = teto - (km / conf) * (teto * 0.2)
    elif km <= maxi:
        pontos = (teto * 0.8) * (1 - (km - conf) / (maxi - conf))
    else:
        pontos = 0.0

    return round(max(pontos, 0.0), 1), km


def _pontos_chance(concurso: dict, teto: float = 20.0) -> tuple[float, str]:
    vagas = concurso.get("vagas_cargo") or concurso.get("vagas_total")
    if not vagas:
        pontos, nota = 8.0, "número de vagas ainda não divulgado"
    elif vagas == 1:
        pontos, nota = 4.0, "vaga única — disputa máxima"
    elif vagas <= 5:
        pontos, nota = 8.0, f"{vagas} vagas — disputa alta"
    elif vagas <= 20:
        pontos, nota = 12.0, f"{vagas} vagas"
    elif vagas <= 100:
        pontos, nota = 15.0, f"{vagas} vagas — bom volume"
    elif vagas <= 500:
        pontos, nota = 17.0, f"{vagas} vagas — volume alto"
    else:
        pontos, nota = 19.0, f"{vagas} vagas — volume muito alto"

    salario = concurso.get("salario") or 0
    if salario > 15000:
        pontos -= 6.0
        nota += "; salário alto atrai concorrência nacional"
    elif salario > 10000:
        pontos -= 3.0
        nota += "; salário alto eleva a concorrência"

    if concurso.get("trilha") == "T1":
        pontos += 3.0
        nota += "; exigência de diploma de engenharia filtra o público"

    return round(min(max(pontos, 0.0), 20.0) * teto / 20.0, 1), nota


def _pontos_retorno(concurso: dict, teto: float = 10.0) -> float:
    s = concurso.get("salario") or 0
    escala = teto / 10.0
    if s < 3000:
        return round(3.0 * escala, 1)
    if s < 5000:
        return round(5.0 * escala, 1)
    if s < 8000:
        return round(7.0 * escala, 1)
    if s < 12000:
        return round(9.0 * escala, 1)
    return round(10.0 * escala, 1)


def _dias_para(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return (datetime.strptime(iso, "%Y-%m-%d").date() - date.today()).days
    except ValueError:
        return None


def _pontos_janela(concurso: dict, prev: dict | None, teto: float) -> tuple[float, str]:
    """Quanto falta para o edital. Previsão manda; sem previsão, cai no status."""
    status = concurso.get("status", "previsto")
    if prev and prev.get("central") is not None:
        falta = prev["central"] - _previsao._hoje_decimal()
        if falta <= 0:
            fator, nota = 1.0, "edital já publicado"
        elif falta <= 0.5:
            fator, nota = 0.9, f"previsto para {prev['rotulo']}"
        elif falta <= 1:
            fator, nota = 0.75, f"previsto para {prev['rotulo']}"
        elif falta <= 2:
            fator, nota = 0.55, f"previsto para {prev['rotulo']}"
        elif falta <= 4:
            fator, nota = 0.3, f"previsto só para {prev['rotulo']}"
        else:
            fator, nota = 0.12, f"previsto só para {prev['rotulo']} — longe demais para ser prioridade"
        if prev.get("atraso_anos") and prev["atraso_anos"] > 0:
            nota += f"; ciclo vencido há {prev['atraso_anos']:.0f} ano(s)"
        return round(teto * fator, 1), nota
    return round(PESO_STATUS.get(status, 5.0) * teto / 10.0, 1), f"situação: {status}"


def _texto_proximidade(concurso: dict, km: float | None, perfil: dict) -> str:
    if km is None:
        return "distância não mapeada"
    base = perfil["base"]["municipio"]
    if concurso.get("lotacao_escolhivel"):
        return f"{km:.0f} km — dá para pedir lotação perto de casa, mesmo com a prova longe"
    return f"{km:.0f} km de {base}"


def horas_edital(concurso: dict, disciplinas: dict) -> float:
    """Carga de estudo que este edital exige, somando as disciplinas que ele cobra."""
    return sum(_horas(disciplinas, c) for c in concurso.get("disciplinas", []))


def pontuar(concurso: dict, perfil: dict, municipios: dict, ciclos: dict | None = None,
            disciplinas: dict | None = None) -> dict:
    """Devolve o concurso enriquecido com score, previsão de edital e explicação."""
    w = pesos(perfil)
    aderencia, motivo_ader = _pontos_aderencia(concurso, perfil)
    proximidade, km = _pontos_proximidade(concurso, perfil, municipios)
    chance, nota_chance = _pontos_chance(concurso, w["chance"])
    retorno = _pontos_retorno(concurso, w["retorno"])
    status = concurso.get("status", "previsto")
    prev = _previsao.prever(concurso, ciclos or {"municipal": 9.0, "estadual": 14.0, "federal": 10.0})
    janela, nota_janela = _pontos_janela(concurso, prev, w["janela"])

    total = aderencia + proximidade + chance + retorno + janela

    # Cargo sem aderência nenhuma não deve subir no ranking por proximidade.
    if aderencia == 0:
        total = min(total, 30.0)

    dias = _dias_para(concurso.get("inscricao_ate"))

    enriquecido = dict(concurso)
    enriquecido.update(
        {
            "score": round(total, 1),
            "componentes": {
                "aderencia": aderencia,
                "proximidade": proximidade,
                "chance": chance,
                "retorno": retorno,
                "janela": janela,
            },
            "explicacao": {
                "aderencia": motivo_ader,
                "proximidade": _texto_proximidade(concurso, km, perfil),
                "chance": nota_chance,
                "retorno": (f"R$ {concurso['salario']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if concurso.get("salario") else "salário não divulgado"),
                "janela": nota_janela,
            },
            "maximos": w,
            "previsao": prev,
            "km": km,
            "km_prova": distancia(municipios, concurso.get("local_prova", "")),
            "lotacao_escolhivel": bool(concurso.get("lotacao_escolhivel")),
            "acionavel": status in ACIONAVEL and aderencia > 0,
            "acao": ROTULO_ACAO.get(status, "MONITORAR"),
            "dias_para_fechar": dias,
            "urgente": dias is not None and 0 <= dias <= 30,
        }
    )

    if disciplinas:
        h = horas_edital(concurso, disciplinas)
        enriquecido["horas_edital"] = h
        enriquecido["reais_por_hora"] = round((concurso.get("salario") or 0) / h, 1) if h else None

    return enriquecido


def ranquear(base: dict | None = None) -> list[dict]:
    base = base or carregar()
    ciclos = {k: v for k, v in base["concursos"].get("ciclos_padrao_anos", {}).items()
              if not k.startswith("_")}
    saida = [pontuar(c, base["perfil"], base["municipios"], ciclos, base["disciplinas"])
             for c in base["concursos"]["concursos"]]
    saida.sort(key=lambda c: (-c["score"], c["orgao"]))
    return saida


# ------------------------------------------------- matriz de conteúdo comum


def _horas(disciplinas: dict, codigo: str) -> float:
    d = disciplinas["disciplinas"].get(codigo)
    return float(d["horas_base"]) if d else 0.0


def _compartilhavel(disciplinas: dict, codigo: str) -> bool:
    d = disciplinas["disciplinas"].get(codigo, {})
    return not d.get("nao_compartilhavel", False)


def sobreposicao(a: dict, b: dict, disciplinas: dict) -> dict:
    """Quanto do conteúdo de dois concursos é o mesmo, medido em horas de estudo."""
    da = {c for c in a.get("disciplinas", []) if _compartilhavel(disciplinas, c)}
    db = {c for c in b.get("disciplinas", []) if _compartilhavel(disciplinas, c)}

    comuns = da & db
    h_comuns = sum(_horas(disciplinas, c) for c in comuns)
    h_a = sum(_horas(disciplinas, c) for c in da)
    h_b = sum(_horas(disciplinas, c) for c in db)
    h_extra = sum(_horas(disciplinas, c) for c in (db - da))

    # Dice: 2 x horas comuns / (horas de A + horas de B). Lê-se diretamente como
    # "percentual do conteúdo que as duas provas têm em comum".
    percentual = round(200 * h_comuns / (h_a + h_b), 1) if (h_a + h_b) else 0.0

    return {
        "percentual": percentual,
        "cobertura_de_b": round(100 * h_comuns / h_b, 1) if h_b else 0.0,
        "horas_comuns": h_comuns,
        "horas_extras": h_extra,
        "disciplinas_comuns": sorted(comuns),
        "disciplinas_extras": sorted(db - da),
    }


def matriz(concursos: list[dict], disciplinas: dict) -> dict:
    ids = [c["id"] for c in concursos]
    celulas: dict[str, dict[str, float]] = {}
    for a in concursos:
        celulas[a["id"]] = {}
        for b in concursos:
            celulas[a["id"]][b["id"]] = (
                100.0 if a["id"] == b["id"] else sobreposicao(a, b, disciplinas)["percentual"]
            )
    return {"ids": ids, "celulas": celulas}


def nucleo_comum(concursos: list[dict], disciplinas: dict) -> list[dict]:
    """Disciplinas ordenadas por quantos concursos uma única rodada de estudo cobre."""
    total = len(concursos) or 1
    linhas = []
    for codigo, d in disciplinas["disciplinas"].items():
        alcance = [c["id"] for c in concursos if codigo in c.get("disciplinas", [])]
        if not alcance:
            continue
        horas = float(d["horas_base"])
        linhas.append(
            {
                "codigo": codigo,
                "nome": d["nome"],
                "eixo": d["eixo"],
                "horas": horas,
                "recorrencia": d.get("recorrencia", 0.5),
                "alcance": len(alcance),
                "cobertura_pct": round(100 * len(alcance) / total),
                "concursos": alcance,
                "roi": round(len(alcance) / horas * 100, 1),
                "ponte": d.get("ponte", False),
                "compartilhavel": not d.get("nao_compartilhavel", False),
                "dica": d.get("dica", ""),
                "topicos": d.get("topicos", []),
            }
        )
    linhas.sort(key=lambda x: (-x["alcance"], -x["roi"]))
    return linhas


def _nomear_bloco(comuns: set[str], semente: dict) -> tuple[str, str]:
    """Rótulo temático do bloco, a partir das disciplinas técnicas que ele compartilha."""
    if {"EC_SAN", "EC_HID"} <= comuns:
        return "Água, saneamento e meio ambiente", "Mesmo miolo técnico: hidráulica, ETA/ETE e licenciamento."
    if "EC_TRA" in comuns:
        return "Infraestrutura e transportes", "Pavimentação, terraplenagem e geotecnia em comum."
    if {"EC_ORC", "EC_EXE"} <= comuns:
        return "Obras públicas e fiscalização", "Orçamento, execução e fiscalização de obra — o seu terreno."
    if any(c.startswith("EC_") for c in comuns):
        return "Engenharia civil — base comum", "Conteúdo técnico compartilhado de engenharia."
    return "Administrativo e gestão pública", "Sem conteúdo técnico pesado: base + legislação."


def blocos(concursos: list[dict], disciplinas: dict, limiar: float = 76.0) -> list[dict]:
    """Agrupa concursos que compartilham conteúdo suficiente para serem estudados juntos."""
    restantes = list(concursos)
    grupos: list[dict] = []

    while restantes:
        semente = restantes.pop(0)
        membros = [semente]
        sobrou = []
        for outro in restantes:
            # Ligação completa: só entra no bloco quem tem sobreposição alta com
            # TODOS os membros, não só com a semente. Blocos menores, porém honestos.
            if all(sobreposicao(m, outro, disciplinas)["percentual"] >= limiar for m in membros):
                membros.append(outro)
            else:
                sobrou.append(outro)
        restantes = sobrou

        codigos = [set(m.get("disciplinas", [])) for m in membros]
        interseccao = set.intersection(*codigos) if codigos else set()
        uniao = set.union(*codigos) if codigos else set()

        rotulo, resumo = _nomear_bloco(interseccao, semente)
        grupos.append(
            {
                "nome": rotulo,
                "resumo": resumo,
                "ancora": semente["orgao"],
                "membros": [
                    {"id": m["id"], "orgao": m["orgao"], "cargo": m["cargo"], "score": m.get("score"), "acao": m.get("acao")}
                    for m in membros
                ],
                "quantidade": len(membros),
                "disciplinas_comuns": sorted(interseccao),
                "horas_comuns": sum(_horas(disciplinas, c) for c in interseccao),
                "horas_total_bloco": sum(_horas(disciplinas, c) for c in uniao),
            }
        )

    grupos.sort(key=lambda g: (-g["quantidade"], -g["horas_comuns"]))
    return grupos


def plano_estudo(concursos: list[dict], disciplinas: dict, horas_semana: float = 15.0) -> dict:
    """Ordem de estudo por retorno: o que cobre mais concursos por hora investida, primeiro."""
    nucleo = nucleo_comum(concursos, disciplinas)
    # Mesmo alcance: vem primeiro a matéria que mais pesa na prova (recorrência),
    # e só então a mais barata em horas.
    ordenado = sorted(nucleo, key=lambda x: (-x["alcance"], -x["recorrencia"], x["horas"]))

    acumulado = 0.0
    cobertos: set[str] = set()
    etapas = []
    total_concursos = {c["id"] for c in concursos}

    for item in ordenado:
        acumulado += item["horas"]
        cobertos |= set(item["concursos"])
        etapas.append(
            {
                **item,
                "horas_acumuladas": acumulado,
                "semanas_acumuladas": round(acumulado / horas_semana, 1) if horas_semana else None,
                "concursos_alcancados": len(cobertos),
                "pct_radar_coberto": round(100 * len(cobertos) / len(total_concursos)) if total_concursos else 0,
            }
        )

    return {
        "horas_semana": horas_semana,
        "horas_total": acumulado,
        "semanas_total": round(acumulado / horas_semana, 1) if horas_semana else None,
        "etapas": etapas,
    }


def painel(selecao: list[str] | None = None, horas_semana: float = 15.0, publico: bool = False) -> dict:
    """Monta o pacote que alimenta a interface.

    publico=True é a versão que vai para fora da máquina: troca o município-base
    pelo rótulo de região, para a página publicada não revelar onde o candidato mora.
    """
    base = carregar()
    todos = ranquear(base)

    if selecao:
        escolhidos = [c for c in todos if c["id"] in set(selecao)]
    else:
        escolhidos = [c for c in todos if c["acionavel"]]

    disciplinas = base["disciplinas"]

    return {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        # Privacidade: o perfil inteiro (experiência, exclusões, salário mínimo) NÃO sai
        # daqui. Só o nome do município-base, que a interface precisa para o cabeçalho.
        "base_label": (base["perfil"].get("privacidade", {}).get("rotulo_publico", "minha base")
                       if publico else base["perfil"]["base"]["municipio"]),
        "raio_confortavel_km": base["perfil"]["base"]["raio_confortavel_km"],
        "pesos_max": pesos(base["perfil"]),
        "atualizado_em": base["concursos"].get("atualizado_em"),
        "status_legenda": base["concursos"].get("status_legenda", {}),
        "concursos": todos,
        "selecionados": [c["id"] for c in escolhidos],
        "matriz": matriz(escolhidos, disciplinas),
        "nucleo_comum": nucleo_comum(escolhidos, disciplinas),
        "blocos": blocos(escolhidos, disciplinas),
        "plano": plano_estudo(escolhidos, disciplinas, horas_semana),
        "disciplinas": disciplinas["disciplinas"],
        "eixos": disciplinas["eixos"],
    }
