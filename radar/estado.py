"""Estado persistente: sinais capturados no rastreio e decisões do candidato."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "dados" / "radar.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS sinais (
    hash          TEXT PRIMARY KEY,
    concurso_id   TEXT,
    titulo        TEXT NOT NULL,
    link          TEXT,
    fonte         TEXT,
    publicado_em  TEXT,
    status        TEXT,
    relevancia    INTEGER DEFAULT 0,
    visto         INTEGER DEFAULT 0,
    criado_em     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisoes (
    concurso_id TEXT PRIMARY KEY,
    decisao     TEXT NOT NULL,
    anotacao    TEXT,
    atualizado  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS progresso (
    disciplina  TEXT PRIMARY KEY,
    situacao    TEXT NOT NULL,
    atualizado  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execucoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rodado_em   TEXT NOT NULL,
    novos       INTEGER DEFAULT 0,
    consultas   INTEGER DEFAULT 0,
    erros       TEXT
);
"""


def conectar() -> sqlite3.Connection:
    BANCO.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(BANCO)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    return con


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def gravar_sinal(con: sqlite3.Connection, sinal: dict) -> bool:
    """Insere um sinal novo. Devolve True se era inédito."""
    try:
        con.execute(
            "INSERT INTO sinais (hash, concurso_id, titulo, link, fonte, publicado_em, status, relevancia, criado_em)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                sinal["hash"],
                sinal.get("concurso_id"),
                sinal["titulo"],
                sinal.get("link"),
                sinal.get("fonte"),
                sinal.get("publicado_em"),
                sinal.get("status"),
                sinal.get("relevancia", 0),
                agora(),
            ),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def listar_sinais(con: sqlite3.Connection, limite: int = 80) -> list[dict]:
    cur = con.execute(
        "SELECT * FROM sinais ORDER BY relevancia DESC, COALESCE(publicado_em, criado_em) DESC LIMIT ?",
        (limite,),
    )
    return [dict(r) for r in cur.fetchall()]


def marcar_vistos(con: sqlite3.Connection) -> None:
    con.execute("UPDATE sinais SET visto = 1")
    con.commit()


def definir_decisao(con: sqlite3.Connection, concurso_id: str, decisao: str, anotacao: str = "") -> None:
    con.execute(
        "INSERT INTO decisoes (concurso_id, decisao, anotacao, atualizado) VALUES (?,?,?,?)"
        " ON CONFLICT(concurso_id) DO UPDATE SET decisao=excluded.decisao,"
        " anotacao=excluded.anotacao, atualizado=excluded.atualizado",
        (concurso_id, decisao, anotacao, agora()),
    )
    con.commit()


def listar_decisoes(con: sqlite3.Connection) -> dict[str, dict]:
    cur = con.execute("SELECT * FROM decisoes")
    return {r["concurso_id"]: dict(r) for r in cur.fetchall()}


def definir_progresso(con: sqlite3.Connection, disciplina: str, situacao: str) -> None:
    con.execute(
        "INSERT INTO progresso (disciplina, situacao, atualizado) VALUES (?,?,?)"
        " ON CONFLICT(disciplina) DO UPDATE SET situacao=excluded.situacao, atualizado=excluded.atualizado",
        (disciplina, situacao, agora()),
    )
    con.commit()


def listar_progresso(con: sqlite3.Connection) -> dict[str, str]:
    cur = con.execute("SELECT disciplina, situacao FROM progresso")
    return {r["disciplina"]: r["situacao"] for r in cur.fetchall()}


def registrar_execucao(con: sqlite3.Connection, novos: int, consultas: int, erros: str = "") -> None:
    con.execute(
        "INSERT INTO execucoes (rodado_em, novos, consultas, erros) VALUES (?,?,?,?)",
        (agora(), novos, consultas, erros),
    )
    con.commit()


def ultima_execucao(con: sqlite3.Connection) -> dict | None:
    cur = con.execute("SELECT * FROM execucoes ORDER BY id DESC LIMIT 1")
    linha = cur.fetchone()
    return dict(linha) if linha else None
