"""Lexer: transforma o texto SQL cru em uma lista plana de tokens.

Escrito à mão em vez de baseado em regex, para que as mensagens de erro possam
apontar a posição exata do caractere e para que as regras dos tokens permaneçam
fáceis de ler e estender.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from picodb.errors import LexError


class TokenType(Enum):
    KEYWORD = auto()
    IDENT = auto()       # nomes de tabelas/colunas
    NUMBER = auto()      # literal inteiro
    STRING = auto()      # 'literal de texto'
    OPERATOR = auto()    # = < > <= >= != and , ( ) *
    EOF = auto()


# Palavras reservadas são comparadas sem diferenciar maiúsculas/minúsculas, mas
# armazenadas em maiúsculo para o parser comparar contra uma única forma canônica.
KEYWORDS = {
    "CREATE", "TABLE", "INSERT", "INTO", "VALUES", "SELECT", "FROM",
    "WHERE", "AND", "OR", "ORDER", "BY", "ASC", "DESC", "LIMIT",
    "DELETE", "UPDATE", "SET", "INT", "TEXT", "GROUP",
    "COUNT", "SUM", "AVG", "MIN", "MAX",
}

# Operadores de dois caracteres precisam ser testados antes dos seus prefixos.
_TWO_CHAR_OPS = {"<=", ">=", "!=", "<>"}
_ONE_CHAR_OPS = set("=<>(),*")


@dataclass(frozen=True)
class Token:
    type: TokenType
    value: str
    pos: int  # índice na string de origem, para mensagens de erro

    def __repr__(self) -> str:  # pragma: no cover - auxiliar de depuração
        return f"Token({self.type.name}, {self.value!r})"


def tokenize(sql: str) -> list[Token]:
    """Converte ``sql`` em tokens, sempre terminados por um token EOF."""
    # Ferramentas do Windows costumam prefixar um BOM UTF-8; removemos para não
    # virar um token perdido.
    sql = sql.lstrip("﻿")
    tokens: list[Token] = []
    i = 0
    n = len(sql)

    while i < n:
        ch = sql[i]

        # Espaço em branco (inclusive quebras de linha) é irrelevante entre tokens.
        if ch.isspace():
            i += 1
            continue

        # Comentários de linha: -- até o fim da linha.
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            continue

        # Literal de string entre aspas simples; '' é uma aspa escapada.
        if ch == "'":
            i, value = _read_string(sql, i)
            tokens.append(Token(TokenType.STRING, value, i))
            continue

        # Números: apenas inteiros (o sistema de tipos só tem INT e TEXT).
        if ch.isdigit():
            start = i
            while i < n and sql[i].isdigit():
                i += 1
            tokens.append(Token(TokenType.NUMBER, sql[start:i], start))
            continue

        # Identificadores / palavras-chave: começam com letra ou sublinhado.
        if ch.isalpha() or ch == "_":
            start = i
            while i < n and (sql[i].isalnum() or sql[i] == "_"):
                i += 1
            word = sql[start:i]
            upper = word.upper()
            if upper in KEYWORDS:
                tokens.append(Token(TokenType.KEYWORD, upper, start))
            else:
                tokens.append(Token(TokenType.IDENT, word, start))
            continue

        # Operadores: tenta primeiro as formas de dois caracteres.
        two = sql[i : i + 2]
        if two in _TWO_CHAR_OPS:
            # Normaliza a grafia SQL "<>" para "!=" para o executor.
            tokens.append(Token(TokenType.OPERATOR, "!=" if two == "<>" else two, i))
            i += 2
            continue
        if ch in _ONE_CHAR_OPS:
            tokens.append(Token(TokenType.OPERATOR, ch, i))
            i += 1
            continue

        raise LexError(f"Caractere inesperado {ch!r} na posição {i}")

    tokens.append(Token(TokenType.EOF, "", n))
    return tokens


def _read_string(sql: str, i: int) -> tuple[int, str]:
    """Lê uma string entre aspas simples começando em ``i`` (a aspa de abertura)."""
    n = len(sql)
    start = i
    i += 1  # pula a aspa de abertura
    chars: list[str] = []
    while i < n:
        c = sql[i]
        if c == "'":
            # Aspa duplicada dentro da string é uma aspa literal.
            if i + 1 < n and sql[i + 1] == "'":
                chars.append("'")
                i += 2
                continue
            return i + 1, "".join(chars)
        chars.append(c)
        i += 1
    raise LexError(f"Literal de string não terminado iniciado na posição {start}")
