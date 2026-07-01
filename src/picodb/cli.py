"""REPL interativo do pico-db.

Lê instruções SQL terminadas em ``;`` (para que uma instrução possa ocupar várias
linhas), roda cada uma e imprime o resultado como uma tabela de texto alinhada.
Meta-comandos começam com ponto: ``.tables``, ``.help``, ``.exit``.
"""

from __future__ import annotations

import argparse
import sys

from picodb.database import Database
from picodb.errors import PicoDBError
from picodb.executor import ResultSet

_PROMPT = "pico-db> "
_CONTINUATION = "    ...> "


def _format_value(value) -> str:
    return "NULL" if value is None else str(value)


def _render(result: ResultSet) -> str:
    """Renderiza um ResultSet como uma tabela de texto alinhada."""
    header = result.columns
    body = [[_format_value(v) for v in row] for row in result.rows]

    widths = [len(h) for h in header]
    for row in body:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(cells: list[str]) -> str:
        return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    lines = [fmt(header), "-+-".join("-" * w for w in widths)]
    lines.extend(fmt(row) for row in body)
    plural = "" if len(body) == 1 else "s"
    lines.append(f"({len(body)} linha{plural})")
    return "\n".join(lines)


def _print_result(result) -> None:
    if isinstance(result, ResultSet):
        print(_render(result))
    elif isinstance(result, int):
        plural = "" if result == 1 else "s"
        print(f"{result} linha{plural} afetada{plural}")
    elif isinstance(result, str):
        print(result)


def _handle_meta(command: str, db: Database) -> bool:
    """Trata um comando com ponto. Retorna False se o REPL deve encerrar."""
    cmd = command.strip().lower()
    if cmd in (".exit", ".quit"):
        return False
    if cmd == ".tables":
        names = sorted(db.tables)
        print("\n".join(names) if names else "(nenhuma tabela)")
    elif cmd == ".help":
        print(
            "Digite instruções SQL terminadas em ';'.\n"
            "Meta-comandos: .tables  .help  .exit"
        )
    else:
        print(f"Comando desconhecido: {command}")
    return True


def repl(db: Database, *, stdin=sys.stdin, stdout=sys.stdout) -> None:
    """Roda o laço lê-avalia-imprime até EOF ou .exit."""
    buffer = ""
    stdout.write("pico-db - digite .help para ajuda, .exit para sair\n")
    while True:
        prompt = _PROMPT if not buffer else _CONTINUATION
        stdout.write(prompt)
        stdout.flush()
        line = stdin.readline()
        if not line:  # EOF (Ctrl-D / Ctrl-Z)
            stdout.write("\n")
            break
        stripped = line.strip()

        if not buffer and stripped.startswith("."):
            if not _handle_meta(stripped, db):
                break
            continue

        buffer += line
        # Executa cada instrução terminada em ';' no buffer.
        while ";" in buffer:
            stmt, buffer = buffer.split(";", 1)
            if not stmt.strip():
                continue
            try:
                _print_result(db.execute(stmt))
            except PicoDBError as exc:
                stdout.write(f"Erro: {exc}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pico-db", description="Um pequeno banco de dados SQL.")
    parser.add_argument(
        "database",
        nargs="?",
        help="Caminho de um arquivo JSON de banco. Omita para um banco em memória.",
    )
    args = parser.parse_args(argv)

    db = Database.open(args.database) if args.database else Database()
    try:
        repl(db)
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
