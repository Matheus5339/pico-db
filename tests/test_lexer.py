import pytest

from picodb.errors import LexError
from picodb.lexer import TokenType, tokenize


def types_and_values(sql):
    return [(t.type, t.value) for t in tokenize(sql)]


def test_keywords_are_uppercased_and_case_insensitive():
    toks = tokenize("select From wHeRe")
    assert [t.value for t in toks[:3]] == ["SELECT", "FROM", "WHERE"]
    assert all(t.type is TokenType.KEYWORD for t in toks[:3])


def test_identifiers_keep_original_case():
    toks = tokenize("SELECT userName FROM Users")
    idents = [t.value for t in toks if t.type is TokenType.IDENT]
    assert idents == ["userName", "Users"]


def test_numbers_and_strings():
    toks = tokenize("INSERT INTO t VALUES (42, 'hello')")
    numbers = [t.value for t in toks if t.type is TokenType.NUMBER]
    strings = [t.value for t in toks if t.type is TokenType.STRING]
    assert numbers == ["42"]
    assert strings == ["hello"]


def test_two_char_operators():
    ops = [t.value for t in tokenize("a <= b >= c != d") if t.type is TokenType.OPERATOR]
    assert ops == ["<=", ">=", "!="]


def test_angle_bracket_not_equal_is_normalized():
    ops = [t.value for t in tokenize("a <> b") if t.type is TokenType.OPERATOR]
    assert ops == ["!="]


def test_escaped_single_quote_in_string():
    toks = tokenize("SELECT 'O''Brien'")
    strings = [t.value for t in toks if t.type is TokenType.STRING]
    assert strings == ["O'Brien"]


def test_line_comment_is_ignored():
    toks = tokenize("SELECT a -- isto é um comentário\nFROM t")
    values = [t.value for t in toks if t.type is not TokenType.EOF]
    assert values == ["SELECT", "a", "FROM", "t"]


def test_leading_utf8_bom_is_stripped():
    # Uma instrução prefixada por BOM deve tokenizar como se o BOM não existisse.
    toks = tokenize("﻿SELECT 1")
    assert [t.value for t in toks if t.type is not TokenType.EOF] == ["SELECT", "1"]


def test_always_ends_with_eof():
    assert tokenize("").pop().type is TokenType.EOF
    assert tokenize("SELECT 1").pop().type is TokenType.EOF


def test_unexpected_character_raises():
    with pytest.raises(LexError):
        tokenize("SELECT @")


def test_unterminated_string_raises():
    with pytest.raises(LexError):
        tokenize("SELECT 'oops")
