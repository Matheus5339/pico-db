"""Fachada do banco: o único ponto de entrada público.

Amarra o pipeline (parse -> execute), é dona do conjunto de tabelas e dos índices
hash, e decide quando persistir e quando reconstruir índices. Manter essa
orquestração aqui permite que o lexer, o parser e o executor fiquem puros e sem
saber da política de storage ou de indexação.
"""

from __future__ import annotations

from picodb import ast_nodes as ast
from picodb.errors import ExecutionError
from picodb.executor import Executor, ResultSet
from picodb.index import HashIndex
from picodb.parser import parse
from picodb.storage import JSONStorage, MemoryStorage, Storage

# Tipos de instrução que alteram dados e portanto exigem persistir + reindexar.
_MUTATING = (ast.CreateTable, ast.Insert, ast.Delete, ast.Update)


class Database:
    def __init__(self, storage: Storage | None = None) -> None:
        self.storage = storage or MemoryStorage()
        self.tables = self.storage.load()
        # {nome_tabela: {nome_coluna: HashIndex}}
        self.indexes: dict[str, dict[str, HashIndex]] = {}

    @classmethod
    def open(cls, path: str) -> Database:
        """Abre (ou cria) um banco persistido em ``path`` como JSON."""
        return cls(JSONStorage(path))

    def execute(self, sql: str):
        """Analisa e roda uma instrução SQL.

        Retorna um :class:`ResultSet` para SELECT, um ``int`` com a contagem de
        linhas afetadas para INSERT/DELETE/UPDATE, ou uma string de status para
        CREATE TABLE.
        """
        node = parse(sql)
        executor = Executor(self.tables, self.indexes)
        result = executor.execute(node)

        if isinstance(node, _MUTATING):
            self._reindex(node.table)
            self.storage.save(self.tables)
        return result

    def create_index(self, table: str, column: str) -> None:
        """Constrói um índice hash em ``table.column`` para acelerar buscas por igualdade.

        Exposto como API programática em vez de SQL nesta versão; uma instrução
        ``CREATE INDEX`` está listada como trabalho futuro.
        """
        tbl = self.tables.get(table)
        if tbl is None:
            raise ExecutionError(f"Tabela inexistente: {table!r}")
        if tbl.column_type(column) is None:
            raise ExecutionError(f"Coluna inexistente {column!r} em {table!r}")
        self.indexes.setdefault(table, {})[column] = HashIndex.from_table(tbl, column)

    def _reindex(self, table: str) -> None:
        """Reconstrói todos os índices de ``table`` após uma mutação."""
        table_indexes = self.indexes.get(table)
        if not table_indexes:
            return
        tbl = self.tables.get(table)
        if tbl is None:
            # A tabela não existe mais (não alcançável hoje; DROP é trabalho futuro).
            del self.indexes[table]
            return
        for index in table_indexes.values():
            index.build(tbl.rows)


__all__ = ["Database", "ResultSet"]
