"""Parser: transforma o fluxo de tokens em uma AST.

Um parser de descida recursiva escrito à mão. Cada método ``_parse_*``
corresponde a uma regra da gramática, o que deixa o subconjunto de SQL suportado
fácil de ler direto no código:

    statement   := create | insert | select | delete | update
    create      := CREATE TABLE ident '(' coldef (',' coldef)* ')'
    insert      := INSERT INTO ident ['(' ident (',' ident)* ')'] VALUES '(' value (',' value)* ')'
    select      := SELECT projection FROM ident [WHERE expr]
                   [GROUP BY ident (',' ident)*] [ORDER BY orderkey (',' orderkey)*] [LIMIT number]
    delete      := DELETE FROM ident [WHERE expr]
    update      := UPDATE ident SET assign (',' assign)* [WHERE expr]

Expressões do WHERE usam precedência: OR < AND < comparação.
"""

from __future__ import annotations

from picodb import ast_nodes as ast
from picodb.errors import ParseError
from picodb.lexer import Token, TokenType, tokenize

_COMPARISONS = {"=", "!=", "<", ">", "<=", ">="}
_AGG_FUNCS = {"COUNT", "SUM", "AVG", "MIN", "MAX"}


def parse(sql: str):
    """Analisa uma única instrução SQL em texto e retorna um nó da AST."""
    return Parser(tokenize(sql)).parse_statement()


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    # --- auxiliares de token ----------------------------------------------

    @property
    def _cur(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _at_end(self) -> bool:
        return self._cur.type is TokenType.EOF

    def _check_kw(self, *keywords: str) -> bool:
        return self._cur.type is TokenType.KEYWORD and self._cur.value in keywords

    def _match_kw(self, *keywords: str) -> bool:
        """Consome o token atual se ele for uma das ``keywords``."""
        if self._check_kw(*keywords):
            self._advance()
            return True
        return False

    def _expect_kw(self, keyword: str) -> Token:
        if not self._check_kw(keyword):
            raise ParseError(f"Esperava {keyword!r} mas encontrou {self._describe(self._cur)}")
        return self._advance()

    def _expect_op(self, op: str) -> Token:
        if self._cur.type is not TokenType.OPERATOR or self._cur.value != op:
            raise ParseError(f"Esperava {op!r} mas encontrou {self._describe(self._cur)}")
        return self._advance()

    def _expect_ident(self) -> str:
        if self._cur.type is not TokenType.IDENT:
            raise ParseError(f"Esperava um nome mas encontrou {self._describe(self._cur)}")
        return self._advance().value

    @staticmethod
    def _describe(tok: Token) -> str:
        if tok.type is TokenType.EOF:
            return "fim da entrada"
        return f"{tok.value!r}"

    # --- despacho de instrução -------------------------------------------

    def parse_statement(self):
        if self._at_end():
            raise ParseError("Instrução vazia")

        if self._check_kw("CREATE"):
            node = self._parse_create()
        elif self._check_kw("INSERT"):
            node = self._parse_insert()
        elif self._check_kw("SELECT"):
            node = self._parse_select()
        elif self._check_kw("DELETE"):
            node = self._parse_delete()
        elif self._check_kw("UPDATE"):
            node = self._parse_update()
        else:
            raise ParseError(f"Início de instrução inesperado: {self._describe(self._cur)}")

        if not self._at_end():
            raise ParseError(f"Entrada extra inesperada: {self._describe(self._cur)}")
        return node

    # --- CREATE TABLE -----------------------------------------------------

    def _parse_create(self) -> ast.CreateTable:
        self._expect_kw("CREATE")
        self._expect_kw("TABLE")
        table = self._expect_ident()
        self._expect_op("(")
        columns = [self._parse_column_def()]
        while self._match_op(","):
            columns.append(self._parse_column_def())
        self._expect_op(")")
        return ast.CreateTable(table=table, columns=columns)

    def _parse_column_def(self) -> ast.ColumnDef:
        name = self._expect_ident()
        if not self._check_kw("INT", "TEXT"):
            raise ParseError(
                f"Esperava o tipo de coluna INT ou TEXT mas encontrou {self._describe(self._cur)}"
            )
        col_type = self._advance().value
        return ast.ColumnDef(name=name, type=col_type)

    # --- INSERT -----------------------------------------------------------

    def _parse_insert(self) -> ast.Insert:
        self._expect_kw("INSERT")
        self._expect_kw("INTO")
        table = self._expect_ident()

        columns: list[str] | None = None
        if self._match_op("("):
            columns = [self._expect_ident()]
            while self._match_op(","):
                columns.append(self._expect_ident())
            self._expect_op(")")

        self._expect_kw("VALUES")
        self._expect_op("(")
        values = [self._parse_literal_value()]
        while self._match_op(","):
            values.append(self._parse_literal_value())
        self._expect_op(")")
        return ast.Insert(table=table, columns=columns, values=values)

    # --- SELECT -----------------------------------------------------------

    def _parse_select(self) -> ast.Select:
        self._expect_kw("SELECT")
        projection = self._parse_projection()
        self._expect_kw("FROM")
        table = self._expect_ident()

        where = self._parse_expression() if self._match_kw("WHERE") else None

        group_by: list[str] = []
        if self._match_kw("GROUP"):
            self._expect_kw("BY")
            group_by.append(self._expect_ident())
            while self._match_op(","):
                group_by.append(self._expect_ident())

        order_by: list[ast.OrderKey] = []
        if self._match_kw("ORDER"):
            self._expect_kw("BY")
            order_by.append(self._parse_order_key())
            while self._match_op(","):
                order_by.append(self._parse_order_key())

        limit: int | None = None
        if self._match_kw("LIMIT"):
            if self._cur.type is not TokenType.NUMBER:
                found = self._describe(self._cur)
                raise ParseError(f"Esperava um número após LIMIT mas encontrou {found}")
            limit = int(self._advance().value)

        return ast.Select(
            table=table,
            projection=projection,
            where=where,
            order_by=order_by,
            limit=limit,
            group_by=group_by,
        )

    def _parse_projection(self) -> list[object]:
        # Um '*' isolado só é válido como único item da projeção.
        if self._match_op("*"):
            return [ast.Star()]

        items = [self._parse_projection_item()]
        while self._match_op(","):
            items.append(self._parse_projection_item())
        return items

    def _parse_projection_item(self):
        # Chamada de agregação, ex.: COUNT(*), SUM(price).
        if self._check_kw(*_AGG_FUNCS):
            func = self._advance().value
            self._expect_op("(")
            if self._match_op("*"):
                arg = None
                if func != "COUNT":
                    raise ParseError(f"{func}(*) não é suportado; apenas COUNT(*)")
            else:
                arg = self._expect_ident()
            self._expect_op(")")
            return ast.Aggregate(func=func, arg=arg)

        return ast.Column(self._expect_ident())

    def _parse_order_key(self) -> ast.OrderKey:
        column = self._expect_ident()
        descending = False
        if self._match_kw("ASC"):
            descending = False
        elif self._match_kw("DESC"):
            descending = True
        return ast.OrderKey(column=column, descending=descending)

    # --- DELETE -----------------------------------------------------------

    def _parse_delete(self) -> ast.Delete:
        self._expect_kw("DELETE")
        self._expect_kw("FROM")
        table = self._expect_ident()
        where = self._parse_expression() if self._match_kw("WHERE") else None
        return ast.Delete(table=table, where=where)

    # --- UPDATE -----------------------------------------------------------

    def _parse_update(self) -> ast.Update:
        self._expect_kw("UPDATE")
        table = self._expect_ident()
        self._expect_kw("SET")
        assignments = [self._parse_assignment()]
        while self._match_op(","):
            assignments.append(self._parse_assignment())
        where = self._parse_expression() if self._match_kw("WHERE") else None
        return ast.Update(table=table, assignments=assignments, where=where)

    def _parse_assignment(self) -> tuple[str, object]:
        column = self._expect_ident()
        self._expect_op("=")
        value = self._parse_literal_value()
        return (column, value)

    # --- expressões (WHERE) ----------------------------------------------

    def _parse_expression(self):
        return self._parse_or()

    def _parse_or(self):
        node = self._parse_and()
        while self._match_kw("OR"):
            right = self._parse_and()
            node = ast.BinaryOp(op="OR", left=node, right=right)
        return node

    def _parse_and(self):
        node = self._parse_comparison()
        while self._match_kw("AND"):
            right = self._parse_comparison()
            node = ast.BinaryOp(op="AND", left=node, right=right)
        return node

    def _parse_comparison(self):
        # Subexpressão entre parênteses.
        if self._match_op("("):
            inner = self._parse_expression()
            self._expect_op(")")
            return inner

        left = self._parse_operand()
        if self._cur.type is TokenType.OPERATOR and self._cur.value in _COMPARISONS:
            op = self._advance().value
            right = self._parse_operand()
            return ast.BinaryOp(op=op, left=left, right=right)
        raise ParseError(
            f"Esperava um operador de comparação mas encontrou {self._describe(self._cur)}"
        )

    def _parse_operand(self):
        if self._cur.type is TokenType.IDENT:
            return ast.Column(self._advance().value)
        return ast.Literal(self._parse_literal_value())

    def _parse_literal_value(self):
        tok = self._cur
        if tok.type is TokenType.NUMBER:
            self._advance()
            return int(tok.value)
        if tok.type is TokenType.STRING:
            self._advance()
            return tok.value
        raise ParseError(f"Esperava um valor literal mas encontrou {self._describe(tok)}")

    # --- pequeno auxiliar de operador ------------------------------------

    def _match_op(self, op: str) -> bool:
        if self._cur.type is TokenType.OPERATOR and self._cur.value == op:
            self._advance()
            return True
        return False
