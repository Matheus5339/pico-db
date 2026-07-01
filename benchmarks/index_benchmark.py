"""Benchmark: índice hash vs. varredura completa para buscas por igualdade.

Constrói uma tabela de N linhas e cronometra a mesma consulta `WHERE col = valor`
com e sem um índice hash. Isso reproduz, a partir de primeiros princípios, o
motivo pelo qual bancos de dados reais constroem índices.

Uso:  uv run python benchmarks/index_benchmark.py [linhas] [buscas]
"""

from __future__ import annotations

import random
import sys
import time

from picodb.database import Database


def build_db(rows: int, distinct_names: int = 50) -> Database:
    db = Database()
    db.execute("CREATE TABLE users (id INT, name TEXT, age INT)")
    for i in range(rows):
        name = f"user{random.randint(0, distinct_names - 1)}"
        age = random.randint(18, 80)
        db.execute(f"INSERT INTO users VALUES ({i}, '{name}', {age})")
    return db


def time_lookups(db: Database, targets: list[str]) -> float:
    """Tempo total de parede (em segundos) para rodar um SELECT por alvo."""
    start = time.perf_counter()
    for name in targets:
        db.execute(f"SELECT id FROM users WHERE name = '{name}'")
    return time.perf_counter() - start


def main(argv: list[str]) -> int:
    rows = int(argv[0]) if len(argv) > 0 else 50_000
    lookups = int(argv[1]) if len(argv) > 1 else 1_000
    distinct = 50

    print(f"Construindo uma tabela de {rows:,} linhas...")
    db = build_db(rows, distinct_names=distinct)
    targets = [f"user{random.randint(0, distinct - 1)}" for _ in range(lookups)]

    scan_seconds = time_lookups(db, targets)

    db.create_index("users", "name")
    index_seconds = time_lookups(db, targets)

    scan_ms = scan_seconds * 1000
    index_ms = index_seconds * 1000
    speedup = scan_seconds / index_seconds if index_seconds else float("inf")

    print(f"\nlinhas: {rows:,}  buscas: {lookups:,}")
    print(f"varredura : {scan_ms:8.1f} ms")
    print(f"índice hash: {index_ms:7.1f} ms")
    print(f"speedup    : ~{speedup:.0f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
