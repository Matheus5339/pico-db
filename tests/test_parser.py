import pytest

from picodb import ast_nodes as ast
from picodb.errors import ParseError
from picodb.parser import parse


def test_create_table():
    node = parse("CREATE TABLE users (id INT, name TEXT)")
    assert isinstance(node, ast.CreateTable)
    assert node.table == "users"
    assert node.columns == [
        ast.ColumnDef("id", "INT"),
        ast.ColumnDef("name", "TEXT"),
    ]


def test_insert_positional():
    node = parse("INSERT INTO users VALUES (1, 'alice')")
    assert isinstance(node, ast.Insert)
    assert node.columns is None
    assert node.values == [1, "alice"]


def test_insert_with_column_list():
    node = parse("INSERT INTO users (name, id) VALUES ('bob', 2)")
    assert node.columns == ["name", "id"]
    assert node.values == ["bob", 2]


def test_select_star():
    node = parse("SELECT * FROM users")
    assert isinstance(node, ast.Select)
    assert node.projection == [ast.Star()]


def test_select_columns_where_order_limit():
    node = parse("SELECT id, name FROM users WHERE age >= 18 ORDER BY name DESC LIMIT 5")
    assert [c.name for c in node.projection] == ["id", "name"]
    assert isinstance(node.where, ast.BinaryOp)
    assert node.where.op == ">="
    assert node.order_by == [ast.OrderKey("name", descending=True)]
    assert node.limit == 5


def test_where_precedence_or_binds_looser_than_and():
    # a = 1 OR b = 2 AND c = 3  ==  a=1 OR (b=2 AND c=3)
    node = parse("SELECT * FROM t WHERE a = 1 OR b = 2 AND c = 3")
    assert node.where.op == "OR"
    assert node.where.right.op == "AND"


def test_parenthesized_where():
    node = parse("SELECT * FROM t WHERE (a = 1 OR b = 2) AND c = 3")
    assert node.where.op == "AND"
    assert node.where.left.op == "OR"


def test_aggregate_projection():
    node = parse("SELECT category, COUNT(*), SUM(price) FROM items GROUP BY category")
    assert node.group_by == ["category"]
    assert isinstance(node.projection[1], ast.Aggregate)
    assert node.projection[1].func == "COUNT"
    assert node.projection[1].arg is None
    assert node.projection[2].func == "SUM"
    assert node.projection[2].arg == "price"


def test_delete_and_update():
    d = parse("DELETE FROM users WHERE id = 1")
    assert isinstance(d, ast.Delete)
    u = parse("UPDATE users SET name = 'x', age = 30 WHERE id = 1")
    assert isinstance(u, ast.Update)
    assert u.assignments == [("name", "x"), ("age", 30)]


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "SELECT",
        "SELECT * FROM",
        "CREATE TABLE t (id BOOL)",       # tipo não suportado
        "INSERT INTO t VALUES (1,)",      # vírgula sobrando
        "SELECT * FROM t WHERE a =",      # operando faltando
        "SELECT * FROM t EXTRA",          # lixo no final
        "COUNT(*) FROM t",                # não é uma instrução
    ],
)
def test_invalid_statements_raise(sql):
    with pytest.raises(ParseError):
        parse(sql)
