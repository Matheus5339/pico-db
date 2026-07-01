"""Definições dos nós da AST.

Dataclasses simples, uma por tipo de instrução, mais os nós de expressão usados
pelas cláusulas WHERE. Mantê-las sem comportamento (sem métodos ``eval``) faz o
executor concentrar toda a lógica de runtime e a AST permanecer um valor puro e
fácil de testar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- Expressões (usadas dentro do WHERE) ----------------------------------

@dataclass(frozen=True)
class Column:
    name: str


@dataclass(frozen=True)
class Literal:
    value: object  # int ou str


@dataclass(frozen=True)
class BinaryOp:
    """Comparação (=, <, ...) ou conectivo booleano (AND, OR)."""

    op: str
    left: object
    right: object


# --- Itens de projeção do SELECT ------------------------------------------

@dataclass(frozen=True)
class Star:
    """O ``*`` em ``SELECT *``."""


@dataclass(frozen=True)
class Aggregate:
    """Uma chamada de agregação como ``COUNT(*)`` ou ``SUM(price)``."""

    func: str            # COUNT | SUM | AVG | MIN | MAX
    arg: str | None      # nome da coluna, ou None para COUNT(*)


@dataclass(frozen=True)
class OrderKey:
    column: str
    descending: bool = False


# --- Instruções -----------------------------------------------------------

@dataclass(frozen=True)
class ColumnDef:
    name: str
    type: str  # "INT" ou "TEXT"


@dataclass(frozen=True)
class CreateTable:
    table: str
    columns: list[ColumnDef]


@dataclass(frozen=True)
class Insert:
    table: str
    columns: list[str] | None  # lista explícita de colunas, ou None p/ posicional
    values: list[object]


@dataclass(frozen=True)
class Select:
    table: str
    projection: list[object]           # Star | Column | Aggregate
    where: object | None = None
    order_by: list[OrderKey] = field(default_factory=list)
    limit: int | None = None
    group_by: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Delete:
    table: str
    where: object | None = None


@dataclass(frozen=True)
class Update:
    table: str
    assignments: list[tuple[str, object]]  # (coluna, valor literal)
    where: object | None = None
