import pytest

from picodb.database import Database
from picodb.errors import ExecutionError
from picodb.executor import ResultSet


@pytest.fixture
def db():
    d = Database()
    d.execute("CREATE TABLE users (id INT, name TEXT, age INT)")
    d.execute("INSERT INTO users VALUES (1, 'alice', 30)")
    d.execute("INSERT INTO users VALUES (2, 'bob', 25)")
    d.execute("INSERT INTO users VALUES (3, 'carol', 30)")
    d.execute("INSERT INTO users (id, name) VALUES (4, 'dan')")  # age -> NULL
    return d


def rows(result: ResultSet):
    return result.rows


def test_create_and_insert_counts(db):
    assert db.execute("INSERT INTO users VALUES (5, 'eve', 40)") == 1
    assert len(db.execute("SELECT * FROM users")) == 5


def test_select_star_columns(db):
    result = db.execute("SELECT * FROM users WHERE id = 1")
    assert result.columns == ["id", "name", "age"]
    assert rows(result) == [[1, "alice", 30]]


def test_projection_subset_and_order(db):
    result = db.execute("SELECT name, id FROM users WHERE id = 2")
    assert result.columns == ["name", "id"]
    assert rows(result) == [["bob", 2]]


def test_where_comparisons(db):
    result = db.execute("SELECT id FROM users WHERE age > 25")
    assert sorted(r[0] for r in result) == [1, 3]


def test_where_and_or(db):
    result = db.execute("SELECT id FROM users WHERE age = 30 AND name = 'alice'")
    assert rows(result) == [[1]]
    result = db.execute("SELECT id FROM users WHERE name = 'bob' OR name = 'carol'")
    assert sorted(r[0] for r in result) == [2, 3]


def test_null_comparisons_are_false(db):
    # dan tem age NULL; NULL > 0 tem que ser falso, então dan é excluído.
    result = db.execute("SELECT id FROM users WHERE age > 0")
    assert 4 not in [r[0] for r in result]


def test_order_by_asc_desc_and_nulls_last(db):
    result = db.execute("SELECT id FROM users ORDER BY age DESC")
    ids = [r[0] for r in result]
    # 30,30 primeiro, depois 25 (id 2), depois NULL (id 4) por último, seja qual for a direção.
    assert ids[-1] == 4
    assert ids[0] in (1, 3)


def test_limit(db):
    result = db.execute("SELECT id FROM users ORDER BY id LIMIT 2")
    assert [r[0] for r in result] == [1, 2]


def test_delete(db):
    assert db.execute("DELETE FROM users WHERE age = 30") == 2
    assert len(db.execute("SELECT * FROM users")) == 2


def test_delete_all(db):
    assert db.execute("DELETE FROM users") == 4
    assert len(db.execute("SELECT * FROM users")) == 0


def test_update(db):
    assert db.execute("UPDATE users SET age = 99 WHERE id = 2") == 1
    result = db.execute("SELECT age FROM users WHERE id = 2")
    assert rows(result) == [[99]]


def test_aggregate_count_star(db):
    result = db.execute("SELECT COUNT(*) FROM users")
    assert rows(result) == [[4]]


def test_aggregate_count_ignores_null(db):
    # COUNT(age) ignora o NULL do dan.
    result = db.execute("SELECT COUNT(age) FROM users")
    assert rows(result) == [[3]]


def test_group_by_with_aggregates(db):
    result = db.execute(
        "SELECT age, COUNT(*) FROM users GROUP BY age ORDER BY age DESC"
    )
    assert result.columns == ["age", "COUNT(*)"]
    # age 30 -> 2, age 25 -> 1, age NULL -> 1
    assert [tuple(r) for r in result][:2] == [(30, 2), (25, 1)]


def test_sum_and_avg(db):
    result = db.execute("SELECT SUM(age), AVG(age) FROM users")
    total, avg = result.rows[0]
    assert total == 85  # 30 + 25 + 30
    assert avg == pytest.approx(85 / 3)


# --- casos de erro --------------------------------------------------------

def test_select_unknown_table():
    with pytest.raises(ExecutionError):
        Database().execute("SELECT * FROM nope")


def test_create_duplicate_table(db):
    with pytest.raises(ExecutionError):
        db.execute("CREATE TABLE users (id INT)")


def test_insert_wrong_arity(db):
    with pytest.raises(ExecutionError):
        db.execute("INSERT INTO users VALUES (1)")


def test_insert_type_mismatch(db):
    with pytest.raises(ExecutionError):
        db.execute("INSERT INTO users VALUES ('x', 'y', 'z')")  # id é INT


def test_unknown_column_in_projection(db):
    with pytest.raises(ExecutionError):
        db.execute("SELECT nope FROM users")


def test_compare_incompatible_types(db):
    with pytest.raises(ExecutionError):
        db.execute("SELECT * FROM users WHERE name > 5")


def test_non_grouped_column_in_aggregate(db):
    with pytest.raises(ExecutionError):
        db.execute("SELECT name, COUNT(*) FROM users")
