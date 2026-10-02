#!/usr/bin/env python3
"""Radar de Concursos — servidor local e linha de comando.

Uso:
    python app.py                 abre a interface no navegador (padrão)
    python app.py rastrear        varre as fontes e grava os sinais novos
    python app.py rastrear --forcar   ignora a trava de fim de semana
    python app.py listar          ranking no terminal
    python app.py exportar        gera dados.json estático em web/
"""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from radar import estado, fontes, nucleo

RAIZ = Path(__file__).resolve().parent
WEB = RAIZ / "web"
PORTA = 8777

TIPOS = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


# ------------------------------------------------------------------ dados


def montar_painel(selecao: list[str] | None = None, horas: float = 15.0, publico: bool = False) -> dict:
    dados = nucleo.painel(selecao, horas, publico)
    con = estado.conectar()
    try:
        decisoes = estado.listar_decisoes(con)
        dados["decisoes"] = {k: v["decisao"] for k, v in decisoes.items()}
        dados["progresso"] = estado.listar_progresso(con)
        dados["sinais"] = estado.listar_sinais(con, 60)
        dados["ultima_execucao"] = estado.ultima_execucao(con)
    finally:
        con.close()

    dados["agenda"] = {
        "roda_hoje": fontes.deve_rodar_hoje(),
        "dia": fontes.nome_do_dia(),
        "regra": "O radar rastreia de segunda a sexta. Sábado e domingo ficam de folga.",
    }

    # Se o usuário já decidiu "fazer" algum concurso, a seleção padrão passa a ser essa.
    aceitos = [k for k, v in dados["decisoes"].items() if v == "fazer"]
    if aceitos and selecao is None:
        return montar_painel(aceitos, horas, publico)

    return dados


def comando_rastrear(forcar: bool = False) -> int:
    if not fontes.deve_rodar_hoje() and not forcar:
        print(f"Hoje é {fontes.nome_do_dia()}. O radar roda de segunda a sexta.")
        print("Use --forcar se quiser rastrear mesmo assim.")
        return 0

    print(f"Rastreando ({fontes.nome_do_dia()})...")
    resultado = fontes.rastrear()

    con = estado.conectar()
    try:
        novos = sum(1 for s in resultado["sinais"] if estado.gravar_sinal(con, s))
        con.commit()
        estado.registrar_execucao(con, novos, resultado["consultas"], "; ".join(resultado["erros"][:5]))
    finally:
        con.close()

    print(f"\n{resultado['consultas']} consultas · {len(resultado['sinais'])} sinais · {novos} novos")
    if resultado["erros"]:
        print(f"{len(resultado['erros'])} fontes falharam (rede ou bloqueio) — o resto seguiu normalmente.")

    for s in resultado["sinais"][:12]:
        marca = {"aberto": "[ABERTO]  ", "iminente": "[IMINENTE]", "autorizado": "[AUTORIZ.]"}.get(s["status"] or "", "[sinal]   ")
        print(f"  {marca} {s['titulo'][:95]}")
    return 0


def comando_listar() -> int:
    for c in nucleo.ranquear():
        if not c["acionavel"]:
            continue
        print(f"{c['score']:>5.1f}  {c['acao']:<11} {c['orgao'][:46]:<46} {c['cargo'][:34]}")
    return 0


def comando_exportar() -> int:
    """Versão estática para hospedar. Sai sem perfil e sem o município-base."""
    dados = montar_painel(publico=True)
    destino = WEB / "dados.json"
    destino.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exportado: {destino}  ({destino.stat().st_size // 1024} KB)")
    return 0


# ---------------------------------------------------------------- servidor


class Manipulador(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silencia o log padrão
        pass

    def _responder(self, corpo: bytes, tipo: str, codigo: int = 200) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, dados: dict, codigo: int = 200) -> None:
        self._responder(json.dumps(dados, ensure_ascii=False).encode("utf-8"), TIPOS[".json"], codigo)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        rota = url.path
        params = parse_qs(url.query)

        if rota in ("/api/painel", "/dados.json"):
            sel = params.get("sel", [""])[0]
            horas = float(params.get("horas", ["15"])[0] or 15)
            selecao = [s for s in sel.split(",") if s] or None
            self._json(montar_painel(selecao, horas))
            return

        if rota == "/api/sinais":
            con = estado.conectar()
            try:
                self._json({"sinais": estado.listar_sinais(con, 100)})
            finally:
                con.close()
            return

        arquivo = WEB / ("index.html" if rota == "/" else rota.lstrip("/"))
        try:
            arquivo = arquivo.resolve()
            arquivo.relative_to(WEB.resolve())
            corpo = arquivo.read_bytes()
        except (OSError, ValueError):
            self._responder(b"Nao encontrado", "text/plain; charset=utf-8", 404)
            return
        self._responder(corpo, TIPOS.get(arquivo.suffix, "application/octet-stream"))

    def do_POST(self) -> None:
        rota = urlparse(self.path).path
        tamanho = int(self.headers.get("Content-Length") or 0)
        try:
            corpo = json.loads(self.rfile.read(tamanho) or b"{}")
        except json.JSONDecodeError:
            self._json({"erro": "json inválido"}, 400)
            return

        con = estado.conectar()
        try:
            if rota == "/api/decisao":
                estado.definir_decisao(con, corpo["id"], corpo["decisao"], corpo.get("anotacao", ""))
                self._json({"ok": True})
            elif rota == "/api/progresso":
                estado.definir_progresso(con, corpo["disciplina"], corpo["situacao"])
                self._json({"ok": True})
            elif rota == "/api/rastrear":
                forcar = bool(corpo.get("forcar"))
                if not fontes.deve_rodar_hoje() and not forcar:
                    self._json({"ok": False, "motivo": f"Hoje é {fontes.nome_do_dia()} — o radar roda de segunda a sexta."})
                    return
                resultado = fontes.rastrear(verboso=False)
                novos = sum(1 for s in resultado["sinais"] if estado.gravar_sinal(con, s))
                con.commit()
                estado.registrar_execucao(con, novos, resultado["consultas"], "; ".join(resultado["erros"][:5]))
                self._json({"ok": True, "novos": novos, "total": len(resultado["sinais"]), "consultas": resultado["consultas"]})
            elif rota == "/api/vistos":
                estado.marcar_vistos(con)
                self._json({"ok": True})
            else:
                self._json({"erro": "rota desconhecida"}, 404)
        except KeyError as exc:
            self._json({"erro": f"campo ausente: {exc}"}, 400)
        finally:
            con.close()


def servir(porta: int = PORTA) -> int:
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), Manipulador)
    endereco = f"http://127.0.0.1:{porta}"
    print(f"Radar de Concursos  ·  {endereco}")
    print(f"Hoje é {fontes.nome_do_dia()} — rastreio {'ativo' if fontes.deve_rodar_hoje() else 'em pausa (fim de semana)'}.")
    print("Ctrl+C para encerrar.")
    threading.Timer(1.0, lambda: webbrowser.open(endereco)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "servir"
    if cmd == "rastrear":
        return comando_rastrear("--forcar" in argv)
    if cmd == "listar":
        return comando_listar()
    if cmd == "exportar":
        return comando_exportar()
    if cmd in ("servir", "-h", "--help"):
        if cmd != "servir":
            print(__doc__)
            return 0
        return servir()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
