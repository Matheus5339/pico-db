"""Camada de storage: como as tabelas vivem em memória e são persistidas.

O motor conversa com uma :class:`Storage` abstrata, então a estratégia de
persistência é um detalhe trocável. Duas implementações acompanham o projeto:

* :class:`MemoryStorage` - nada em disco, útil para testes e benchmarks.
* :class:`JSONStorage`    - o banco inteiro serializado em um único arquivo JSON.

O JSON foi escolhido para o MVP porque é trivial de inspecionar e depurar. Seu
custo (o arquivo inteiro é reescrito a cada mutação) é um trade-off deliberado e
documentado; veja o README. A interface abstrata é o que permite trocar depois
por um motor paginado append-only sem tocar no executor.
"""

from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from picodb import ast_nodes as ast


@dataclass
class Table:
    """Uma tabela em memória: esquema mais linhas indexadas por nome de coluna."""

    name: str
    columns: list[ast.ColumnDef]
    rows: list[dict] = field(default_factory=list)

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def column_type(self, name: str) -> str | None:
        for c in self.columns:
            if c.name == name:
                return c.type
        return None

    # --- (de)serialização --------------------------------------------

    def to_dict(self) -> dict:
        return {
            "columns": [{"name": c.name, "type": c.type} for c in self.columns],
            "rows": self.rows,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict) -> Table:
        columns = [ast.ColumnDef(name=c["name"], type=c["type"]) for c in data["columns"]]
        return cls(name=name, columns=columns, rows=list(data.get("rows", [])))


class Storage(ABC):
    """Interface de persistência da qual o executor depende."""

    @abstractmethod
    def load(self) -> dict[str, Table]:
        """Retorna todas as tabelas, indexadas por nome."""

    @abstractmethod
    def save(self, tables: dict[str, Table]) -> None:
        """Persiste o conjunto completo de tabelas."""


class MemoryStorage(Storage):
    """Mantém tudo em RAM. Nada sobrevive à saída do processo."""

    def __init__(self) -> None:
        self._tables: dict[str, Table] = {}

    def load(self) -> dict[str, Table]:
        return self._tables

    def save(self, tables: dict[str, Table]) -> None:
        self._tables = tables


class JSONStorage(Storage):
    """Serializa o banco inteiro em um único arquivo JSON."""

    def __init__(self, path: str) -> None:
        self.path = path

    def load(self) -> dict[str, Table]:
        if not os.path.exists(self.path):
            return {}
        with open(self.path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return {name: Table.from_dict(name, data) for name, data in raw.items()}

    def save(self, tables: dict[str, Table]) -> None:
        raw = {name: table.to_dict() for name, table in tables.items()}
        # Escreve num arquivo temporário e faz replace atômico, para que uma
        # falha no meio da escrita nunca deixe um banco pela metade (corrompido).
        directory = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(raw, fh, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
