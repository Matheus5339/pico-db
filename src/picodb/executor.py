"""Executor: roda um nó da AST contra as tabelas em memória.

O executor é o único componente que conhece a semântica de runtime: checagem de
tipos, avaliação de predicados, agregação e ordenação. Ele lê e muta o dict
``tables`` que recebe, mas delega persistência e manutenção de índice ao chamador
(:class:`picodb.database.Database`), mantendo esta classe livre de I/O.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

from picodb import ast_nodes as ast
from picodb.errors import ExecutionError
from picodb.index import HashIndex
from picodb.storage import Table

_COMPARATORS = {
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
}


@dataclass
class ResultSet:
    """A saída de um SELECT: nomes de colunas mais tuplas de linhas."""

    columns: list[str]
    rows: list[list]

    def __iter__(self):
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)


class Executor:
    def __init__(
        self,
        tables: dict[str, Table],
        indexes: dict[str, dict[str, HashIndex]] | None = None,
    ) -> None:
        self.tables = tables
        self.indexes = indexes or {}

    def execute(self, node):
        """Despacha para o handler do tipo de instrução de ``node``."""
        if isinstance(node, ast.CreateTable):
            return self._create(node)
        if isinstance(node, ast.Insert):
            return self._insert(node)
        if isinstance(node, ast.Select):
            return self._select(node)
        if isinstance(node, ast.Delete):
            return self._delete(node)
        if isinstance(node, ast.Update):
            return self._update(node)
        raise ExecutionError(f"Não sei executar nó do tipo {type(node).__name__}")

    # --- auxiliares -------------------------------------------------------

    def _require_table(self, name: str) -> Table:
        table = self.tables.get(name)
        if table is None:
            raise ExecutionError(f"Tabela inexistente: {name!r}")
        return table

    @staticmethod
    def _check_type(col_type: str, value, column: str) -> None:
        if value is None:
            return
        if col_type == "INT" and not isinstance(value, int):
            raise ExecutionError(f"Coluna {column!r} é INT mas recebeu {value!r}")
        if col_type == "TEXT" and not isinstance(value, str):
            raise ExecutionError(f"Coluna {column!r} é TEXT mas recebeu {value!r}")

    # --- CREATE TABLE -----------------------------------------------------

    def _create(self, node: ast.CreateTable) -> str:
        if node.table in self.tables:
            raise ExecutionError(f"Tabela já existe: {node.table!r}")
        names = [c.name for c in node.columns]
        if len(names) != len(set(names)):
            raise ExecutionError(f"Nome de coluna duplicado na tabela {node.table!r}")
        self.tables[node.table] = Table(name=node.table, columns=list(node.columns))
        return f"Tabela {node.table!r} criada"

    # --- INSERT -----------------------------------------------------------

    def _insert(self, node: ast.Insert) -> int:
        table = self._require_table(node.table)

        if node.columns is None:
            # Insert posicional: um valor por coluna, na ordem declarada.
            if len(node.values) != len(table.columns):
                raise ExecutionError(
                    f"Tabela {node.table!r} tem {len(table.columns)} colunas "
                    f"mas foram passados {len(node.values)} valores"
                )
            target = table.column_names
        else:
            target = node.columns
            if len(node.columns) != len(node.values):
                raise ExecutionError("A quantidade de colunas não bate com a de valores")
            for name in node.columns:
                if table.column_type(name) is None:
                    raise ExecutionError(f"Coluna inexistente {name!r} em {node.table!r}")

        row: dict = {name: None for name in table.column_names}
        # As quantidades já foram validadas acima, então strict=True é rede de
        # segurança, não risco.
        for name, value in zip(target, node.values, strict=True):
            self._check_type(table.column_type(name), value, name)
            row[name] = value

        table.rows.append(row)
        return 1

    # --- SELECT -----------------------------------------------------------

    def _select(self, node: ast.Select) -> ResultSet:
        table = self._require_table(node.table)
        rows = self._scan(table, node.where)
        rows = [r for r in rows if self._matches(node.where, r)]

        is_aggregate = node.group_by or any(
            isinstance(item, ast.Aggregate) for item in node.projection
        )
        if is_aggregate:
            return self._aggregate_select(node, table, rows)

        columns = self._projection_columns(node, table)
        rows = self._order(rows, node.order_by, table)
        if node.limit is not None:
            rows = rows[: node.limit]
        out_rows = [[r[name] for name in columns] for r in rows]
        return ResultSet(columns=columns, rows=out_rows)

    def _projection_columns(self, node: ast.Select, table: Table) -> list[str]:
        columns: list[str] = []
        for item in node.projection:
            if isinstance(item, ast.Star):
                columns.extend(table.column_names)
            elif isinstance(item, ast.Column):
                if table.column_type(item.name) is None:
                    raise ExecutionError(f"Coluna inexistente {item.name!r} em {node.table!r}")
                columns.append(item.name)
            else:  # pragma: no cover - protegido pelo ramo is_aggregate
                raise ExecutionError("Agregação misturada com colunas simples sem GROUP BY")
        return columns

    def _scan(self, table: Table, where) -> list[dict]:
        """Linhas candidatas para ``where``, usando índice hash quando possível.

        Só um predicado de topo ``col = literal`` pode ser servido por um índice;
        qualquer outra coisa cai numa varredura completa. O predicado ainda é
        aplicado depois, então o índice é apenas uma otimização, nunca uma
        dependência de corretude.
        """
        indexed = self._indexed_equality(table, where)
        if indexed is not None:
            column, value = indexed
            return self.indexes[table.name][column].lookup(value)
        return table.rows

    def _indexed_equality(self, table: Table, where):
        if not isinstance(where, ast.BinaryOp) or where.op != "=":
            return None
        table_indexes = self.indexes.get(table.name)
        if not table_indexes:
            return None
        # Aceita tanto `col = valor` quanto `valor = col`.
        if isinstance(where.left, ast.Column) and isinstance(where.right, ast.Literal):
            col, lit = where.left.name, where.right.value
        elif isinstance(where.right, ast.Column) and isinstance(where.left, ast.Literal):
            col, lit = where.right.name, where.left.value
        else:
            return None
        if col in table_indexes:
            return col, lit
        return None

    def _aggregate_select(self, node: ast.Select, table: Table, rows: list[dict]) -> ResultSet:
        for col in node.group_by:
            if table.column_type(col) is None:
                raise ExecutionError(f"Coluna inexistente {col!r} em {node.table!r}")

        # Toda coluna simples na projeção precisa ser uma coluna de agrupamento.
        for item in node.projection:
            if isinstance(item, ast.Column) and item.name not in node.group_by:
                raise ExecutionError(
                    f"Coluna {item.name!r} precisa aparecer no GROUP BY ou numa agregação"
                )
            if isinstance(item, ast.Star):
                raise ExecutionError("SELECT * não pode ser combinado com agregação")

        # Particiona as linhas em grupos pela chave dos valores do GROUP BY.
        groups: dict[tuple, list[dict]] = {}
        order: list[tuple] = []
        for row in rows:
            key = tuple(row[c] for c in node.group_by)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(row)
        if not node.group_by and not order:
            # Agregar sem GROUP BY sobre zero linhas ainda produz uma linha.
            order = [()]
            groups[()] = []

        columns = [self._column_label(item) for item in node.projection]
        out_rows: list[list] = []
        for key in order:
            group_rows = groups[key]
            out_rows.append([self._eval_projection(item, group_rows) for item in node.projection])

        result = ResultSet(columns=columns, rows=out_rows)
        # ORDER BY / LIMIT sobre a saída agregada operam nas colunas rotuladas.
        if node.order_by:
            result.rows = self._order_labelled(result, node.order_by)
        if node.limit is not None:
            result.rows = result.rows[: node.limit]
        return result

    @staticmethod
    def _column_label(item) -> str:
        if isinstance(item, ast.Column):
            return item.name
        if isinstance(item, ast.Aggregate):
            return f"{item.func}({item.arg if item.arg is not None else '*'})"
        raise ExecutionError("Item de projeção não suportado na agregação")

    def _eval_projection(self, item, group_rows: list[dict]):
        if isinstance(item, ast.Column):
            # Garantidamente uma coluna de agrupamento, logo constante no grupo.
            return group_rows[0][item.name] if group_rows else None
        if isinstance(item, ast.Aggregate):
            return self._eval_aggregate(item, group_rows)
        raise ExecutionError("Item de projeção não suportado na agregação")

    def _eval_aggregate(self, agg: ast.Aggregate, rows: list[dict]):
        if agg.func == "COUNT":
            if agg.arg is None:
                return len(rows)
            return sum(1 for r in rows if r[agg.arg] is not None)

        values = [r[agg.arg] for r in rows if r[agg.arg] is not None]
        if agg.func == "MIN":
            return min(values) if values else None
        if agg.func == "MAX":
            return max(values) if values else None

        # SUM / AVG exigem entrada numérica.
        for v in values:
            if not isinstance(v, int):
                raise ExecutionError(f"{agg.func} exige uma coluna numérica, recebeu {v!r}")
        if agg.func == "SUM":
            return sum(values)
        if agg.func == "AVG":
            return sum(values) / len(values) if values else None
        raise ExecutionError(f"Agregação desconhecida {agg.func!r}")

    def _order(self, rows: list[dict], order_by, table: Table) -> list[dict]:
        if not order_by:
            return rows
        for key in order_by:
            if table.column_type(key.column) is None:
                raise ExecutionError(f"Coluna inexistente {key.column!r} em {table.name!r}")
        return sorted(rows, key=self._sort_key(order_by, lambda r, c: r[c]))

    def _order_labelled(self, result: ResultSet, order_by) -> list[list]:
        index_of = {name: i for i, name in enumerate(result.columns)}
        for key in order_by:
            if key.column not in index_of:
                raise ExecutionError(f"ORDER BY em coluna de saída desconhecida {key.column!r}")
        return sorted(result.rows, key=self._sort_key(order_by, lambda r, c: r[index_of[c]]))

    @staticmethod
    def _sort_key(order_by, get):
        """Monta uma chave de comparação honrando a direção por chave, NULLs por último.

        Usa-se um comparador customizado (em vez de uma chave de tupla) porque os
        NULLs precisam ficar por último independentemente de ASC/DESC, então sua
        posição não pode ser invertida por um ``reverse`` por chave.
        """

        def cmp(r1, r2):
            for key in order_by:
                a, b = get(r1, key.column), get(r2, key.column)
                if a is None and b is None:
                    continue
                if a is None:  # NULLs sempre ordenam por último
                    return 1
                if b is None:
                    return -1
                if a == b:
                    continue
                result = -1 if a < b else 1
                return -result if key.descending else result
            return 0

        return functools.cmp_to_key(cmp)

    # --- DELETE -----------------------------------------------------------

    def _delete(self, node: ast.Delete) -> int:
        table = self._require_table(node.table)
        keep = [r for r in table.rows if not self._matches(node.where, r)]
        removed = len(table.rows) - len(keep)
        table.rows = keep
        return removed

    # --- UPDATE -----------------------------------------------------------

    def _update(self, node: ast.Update) -> int:
        table = self._require_table(node.table)
        for column, value in node.assignments:
            col_type = table.column_type(column)
            if col_type is None:
                raise ExecutionError(f"Coluna inexistente {column!r} em {node.table!r}")
            self._check_type(col_type, value, column)

        count = 0
        for row in table.rows:
            if self._matches(node.where, row):
                for column, value in node.assignments:
                    row[column] = value
                count += 1
        return count

    # --- avaliação de predicado ------------------------------------------

    def _matches(self, where, row: dict) -> bool:
        if where is None:
            return True
        return bool(self._eval(where, row))

    def _eval(self, node, row: dict):
        if isinstance(node, ast.BinaryOp):
            if node.op == "AND":
                return self._eval(node.left, row) and self._eval(node.right, row)
            if node.op == "OR":
                return self._eval(node.left, row) or self._eval(node.right, row)
            return self._eval_comparison(node, row)
        raise ExecutionError(f"Não sei avaliar nó {type(node).__name__} no WHERE")

    def _eval_comparison(self, node: ast.BinaryOp, row: dict) -> bool:
        left = self._operand(node.left, row)
        right = self._operand(node.right, row)
        # Semântica de NULL do SQL (simplificada): qualquer comparação com NULL é falsa.
        if left is None or right is None:
            return False
        if isinstance(left, int) != isinstance(right, int):
            raise ExecutionError(f"Não posso comparar {left!r} e {right!r} de tipos diferentes")
        return _COMPARATORS[node.op](left, right)

    def _operand(self, node, row: dict):
        if isinstance(node, ast.Column):
            if node.name not in row:
                raise ExecutionError(f"Coluna inexistente {node.name!r}")
            return row[node.name]
        if isinstance(node, ast.Literal):
            return node.value
        raise ExecutionError(f"Operando inesperado {type(node).__name__}")
