import os

import pytest

from picodb.database import Database
from picodb.errors import ExecutionError
from picodb.index import HashIndex
from picodb.storage import JSONStorage


def _seed(db):
    db.execute("CREATE TABLE users (id INT, name TEXT)")
    db.execute("INSERT INTO users VALUES (1, 'alice')")
    db.execute("INSERT INTO users VALUES (2, 'bob')")


def test_json_storage_round_trip(tmp_path):
    path = os.path.join(tmp_path, "db.json")
    db = Database.open(path)
    _seed(db)

    # Um Database novo aberto no mesmo arquivo deve enxergar os dados persistidos.
    reopened = Database.open(path)
    result = reopened.execute("SELECT name FROM users ORDER BY id")
    assert [r[0] for r in result] == ["alice", "bob"]


def test_json_storage_atomic_write_leaves_no_tmp(tmp_path):
    path = os.path.join(tmp_path, "db.json")
    db = Database.open(path)
    _seed(db)
    leftovers = [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
    assert leftovers == []


def test_hash_index_lookup_matches_scan():
    db = Database()
    db.execute("CREATE TABLE t (id INT, name TEXT)")
    for i in range(100):
        db.execute(f"INSERT INTO t VALUES ({i}, 'n{i % 5}')")
    db.create_index("t", "name")

    indexed = db.execute("SELECT id FROM t WHERE name = 'n3'")
    ids = sorted(r[0] for r in indexed)
    assert ids == [i for i in range(100) if i % 5 == 3]


def test_index_stays_correct_after_mutations():
    db = Database()
    db.execute("CREATE TABLE t (id INT, name TEXT)")
    db.execute("INSERT INTO t VALUES (1, 'x')")
    db.create_index("t", "name")

    db.execute("INSERT INTO t VALUES (2, 'x')")
    db.execute("INSERT INTO t VALUES (3, 'y')")
    db.execute("DELETE FROM t WHERE id = 1")
    db.execute("UPDATE t SET name = 'y' WHERE id = 2")

    # Após as mutações, só os ids 3 e 2 têm name 'y'; nenhum tem 'x'.
    ys = sorted(r[0] for r in db.execute("SELECT id FROM t WHERE name = 'y'"))
    assert ys == [2, 3]
    assert len(db.execute("SELECT id FROM t WHERE name = 'x'")) == 0


def test_create_index_unknown_table():
    with pytest.raises(ExecutionError):
        Database().create_index("nope", "col")


def test_hash_index_ignores_nulls():
    idx = HashIndex("name")
    idx.build([{"name": None}, {"name": "a"}])
    assert idx.lookup(None) == []
    assert len(idx.lookup("a")) == 1


def test_load_missing_file_is_empty(tmp_path):
    storage = JSONStorage(os.path.join(tmp_path, "missing.json"))
    assert storage.load() == {}
