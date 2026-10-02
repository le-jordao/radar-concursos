"""Coleta de sinais sobre editais. Só biblioteca padrão — nada para instalar.

A fonte principal é o feed RSS de notícias do Google, que indexa em tempo quase real
os portais de concurso, diários oficiais e imprensa local. É o caminho mais confiável
para capturar um edital que "ameaça abrir": a notícia de autorização ou de contratação
de banca costuma sair semanas antes da publicação do edital.
"""

from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime
from email.utils import parsedate_to_datetime

from .nucleo import carregar, sem_acento

AGENTE = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RadarConcursos/1.0"
TEMPO_LIMITE = 20
JANELA_DIAS = 150  # notícia mais velha que isso não é mais sinal de edital

# Palavras que indicam em que fase o concurso está. Ordem importa: a primeira que
# casar define o status, da fase mais avançada para a mais inicial.
PADROES_STATUS: list[tuple[str, str]] = [
    (r"inscri\w+ (abert|prorrog)", "aberto"),
    (r"(sai[u]?|publicad[oa]|divulgad[oa]) .{0,20}edital", "iminente"),
    (r"edital (public|divulg|sai)", "iminente"),
    (r"banca (definid|escolhid|contratad)", "iminente"),
    (r"organizador[a]? (definid|escolhid)", "iminente"),
    (r"(autorizad|aprovad)[oa] .{0,30}concurso", "autorizado"),
    (r"concurso .{0,30}(autorizad|aprovad)", "autorizado"),
    (r"comiss[aã]o (formad|constitu|design)", "autorizado"),
    (r"(solicitad|pedido de|previst)", "previsto"),
    (r"gabarito|resultado|convocaç|homologa", "posterior"),
]

PESO_STATUS_SINAL = {"aberto": 100, "iminente": 80, "autorizado": 60, "previsto": 35, "posterior": 5}

CARGOS_CHAVE = [
    "engenheiro civil",
    "engenharia civil",
    "engenheiro",
    "fiscal de obras",
    "fiscal de posturas",
    "analista de infraestrutura",
    "arquiteto",
    "agente administrativo",
    "assistente administrativo",
    "gestao publica",
    "esporte",
]

RUIDO = ["gabarito", "resultado final", "convocacao", "posse dos aprovados", "homologado o resultado"]


# ------------------------------------------------------------------- agenda


def deve_rodar_hoje(quando: date | None = None) -> bool:
    """Segunda a sexta. Sábado e domingo o radar fica parado."""
    dia = (quando or date.today()).weekday()
    return dia < 5


def nome_do_dia(quando: date | None = None) -> str:
    nomes = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
    return nomes[(quando or date.today()).weekday()]


# -------------------------------------------------------------------- busca


def _baixar(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE, "Accept-Language": "pt-BR,pt;q=0.9"})
    with urllib.request.urlopen(req, timeout=TEMPO_LIMITE) as resp:
        return resp.read()


def _url_google_news(consulta: str) -> str:
    q = urllib.parse.quote_plus(consulta)
    return f"https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"


def _classificar(titulo: str) -> str | None:
    t = sem_acento(titulo)
    for padrao, status in PADROES_STATUS:
        if re.search(padrao, t):
            return status
    return None


def _relevancia(titulo: str, status: str | None, alvo: str, municipios_proximos: set[str]) -> int:
    t = sem_acento(titulo)
    nota = PESO_STATUS_SINAL.get(status or "", 20)

    # Notícia que cita um ano passado quase sempre é de ciclo encerrado.
    ano_atual = date.today().year
    anos = {int(a) for a in re.findall(r"\b(20\d{2})\b", t)}
    if anos and max(anos) < ano_atual:
        nota -= 60

    if any(r in t for r in RUIDO):
        nota -= 40
    if any(c in t for c in CARGOS_CHAVE):
        nota += 25
    if sem_acento(alvo) in t:
        nota += 15
    if any(m in t for m in municipios_proximos):
        nota += 20
    if "concurso" not in t and "edital" not in t and "seletivo" not in t:
        nota -= 30

    return max(nota, 0)


def _data_iso(texto: str | None) -> str | None:
    if not texto:
        return None
    try:
        return parsedate_to_datetime(texto).date().isoformat()
    except (TypeError, ValueError):
        return None


def consultas_do_perfil(base: dict | None = None) -> list[tuple[str, str]]:
    """Monta a lista de buscas a partir do perfil: (alvo, consulta)."""
    base = base or carregar()
    perfil = base["perfil"]
    municipios = base["municipios"]
    maxi = perfil["base"]["raio_maximo_km"]

    ano = date.today().year
    consultas: list[tuple[str, str]] = []

    # 1. Todo município dentro do raio máximo.
    for nome, km in municipios["distancias_km"].items():
        if km <= maxi and not nome.lower().startswith(("nacional", "estadual", "cabo frio (")):
            consultas.append((nome, f'concurso público "{nome}" RJ edital {ano}'))

    # 2. Órgãos já no radar, para acompanhar a evolução de fase.
    for c in base["concursos"]["concursos"]:
        if c.get("status") in {"encerrado"}:
            continue
        sigla = c["orgao"].split("—")[0].strip()
        consultas.append((sigla, f'concurso "{sigla}" edital {ano}'))

    # 3. Buscas abertas por cargo, para pegar o que ainda não está na base.
    consultas.append(("Engenheiro Civil RJ", f'concurso "engenheiro civil" "Rio de Janeiro" edital {ano}'))
    consultas.append(("Fiscal de Obras RJ", f'concurso "fiscal de obras" RJ edital {ano}'))
    consultas.append(("Região dos Lagos", f'concurso público "Região dos Lagos" edital {ano}'))

    # Remove duplicatas preservando a ordem.
    vistos, unicas = set(), []
    for alvo, q in consultas:
        if q not in vistos:
            vistos.add(q)
            unicas.append((alvo, q))
    return unicas


def _casar_concurso(titulo: str, base: dict) -> str | None:
    t = sem_acento(titulo)
    melhor, tamanho = None, 0
    for c in base["concursos"]["concursos"]:
        for pedaco in (c["orgao"].split("—")[0], c.get("local_prova", "")):
            chave = sem_acento(pedaco).strip()
            if len(chave) > 3 and chave in t and len(chave) > tamanho:
                melhor, tamanho = c["id"], len(chave)
    return melhor


def rastrear(base: dict | None = None, limite_consultas: int | None = None, verboso: bool = True) -> dict:
    """Executa a varredura e devolve os sinais encontrados."""
    base = base or carregar()
    municipios_proximos = {
        sem_acento(n)
        for n, km in base["municipios"]["distancias_km"].items()
        if km <= base["perfil"]["base"]["raio_confortavel_km"]
    }

    consultas = consultas_do_perfil(base)
    if limite_consultas:
        consultas = consultas[:limite_consultas]

    sinais: list[dict] = []
    erros: list[str] = []

    for i, (alvo, consulta) in enumerate(consultas, 1):
        if verboso:
            print(f"  [{i:>2}/{len(consultas)}] {alvo}")
        try:
            bruto = _baixar(_url_google_news(consulta))
            raiz = ET.fromstring(bruto)
        except (urllib.error.URLError, ET.ParseError, OSError) as exc:
            erros.append(f"{alvo}: {exc}")
            continue

        for item in raiz.iterfind(".//item"):
            titulo = (item.findtext("title") or "").strip()
            if not titulo:
                continue
            link = (item.findtext("link") or "").strip()
            publicado = _data_iso(item.findtext("pubDate"))
            if publicado and (date.today() - date.fromisoformat(publicado)).days > JANELA_DIAS:
                continue
            status = _classificar(titulo)
            nota = _relevancia(titulo, status, alvo, municipios_proximos)
            if nota < 45:
                continue

            sinais.append(
                {
                    "hash": hashlib.sha1(titulo.encode("utf-8")).hexdigest(),
                    "concurso_id": _casar_concurso(titulo, base),
                    "titulo": titulo,
                    "link": link,
                    "fonte": alvo,
                    "publicado_em": publicado,
                    "status": status,
                    "relevancia": nota,
                }
            )

    # Deduplica por hash mantendo a maior relevância.
    unicos: dict[str, dict] = {}
    for s in sinais:
        if s["hash"] not in unicos or s["relevancia"] > unicos[s["hash"]]["relevancia"]:
            unicos[s["hash"]] = s

    return {
        "rodado_em": datetime.now().isoformat(timespec="seconds"),
        "consultas": len(consultas),
        "sinais": sorted(unicos.values(), key=lambda s: -s["relevancia"]),
        "erros": erros,
    }
