"""Um índice hash simples em memória.

Mapeia cada valor distinto de uma coluna para a lista de linhas que contêm aquele
valor, transformando ``WHERE col = x`` de uma varredura O(n) em uma busca O(1) em
média.

As linhas são armazenadas por referência (os mesmos objetos dict que a tabela
guarda), então um UPDATE in-place em uma coluna *não indexada* é refletido
automaticamente. Alterar uma coluna indexada, ou inserir/remover linhas, exige
uma reconstrução - que a :class:`~picodb.database.Database` dispara após cada
mutação. Isso mantém esta classe pequena e correta ao custo de manutenção O(n) do
índice, um trade-off aceitável já que as escritas já pagam O(n) pela persistência
JSON.

Somente igualdade: índices hash não respondem a consultas de intervalo (``<``,
``>``); uma B-tree responderia, e isso está anotado como trabalho futuro no README.
"""

from __future__ import annotations

from picodb.storage import Table


class HashIndex:
    def __init__(self, column: str) -> None:
        self.column = column
        self._buckets: dict[object, list[dict]] = {}

    def build(self, rows: list[dict]) -> None:
        """Descarta e reconstrói o índice a partir de ``rows``."""
        self._buckets = {}
        for row in rows:
            self._add(row)

    def _add(self, row: dict) -> None:
        key = row.get(self.column)
        if key is None:
            return  # NULLs nunca são retornados por um predicado de igualdade
        self._buckets.setdefault(key, []).append(row)

    def lookup(self, value) -> list[dict]:
        """Linhas cuja coluna indexada é igual a ``value`` (lista vazia se nenhuma)."""
        return self._buckets.get(value, [])

    @classmethod
    def from_table(cls, table: Table, column: str) -> HashIndex:
        index = cls(column)
        index.build(table.rows)
        return index
