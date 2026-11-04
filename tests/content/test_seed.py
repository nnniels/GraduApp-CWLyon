import sqlite3
from pathlib import Path

import pytest

from graduapp.content.loader import load_content
from graduapp.db.connection import connect, init_db
from graduapp.db.seed import SeedError, seed

CONTENT_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "content"


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    return c


@pytest.fixture
def content():
    return load_content(CONTENT_DIR)


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_seed_loads_everything(conn, content):
    seed(conn, content)
    assert count(conn, "step") == 3
    assert count(conn, "itinerary_step") == 6
    assert count(conn, "team_state") == 2
    assert count(conn, "challenge") == 4 + 3


def test_seed_is_idempotent(conn, content):
    seed(conn, content)
    before = [count(conn, t) for t in ("step", "challenge", "itinerary_step", "step_unlock", "team")]
    seed(conn, content)
    assert before == [count(conn, t) for t in ("step", "challenge", "itinerary_step", "step_unlock", "team")]


def test_seed_keeps_renamed_team(conn, content):
    seed(conn, content)
    conn.execute("UPDATE team SET name = 'The Foxes' WHERE id = 'team-1'")
    seed(conn, content)
    assert conn.execute("SELECT name FROM team WHERE id = 'team-1'").fetchone()[0] == "The Foxes"


def test_seed_refuses_after_start(conn, content):
    seed(conn, content)
    conn.execute("UPDATE team_state SET step_index = 0, phase = 'GOING' WHERE team_id = 'team-1'")
    with pytest.raises(SeedError):
        seed(conn, content)
    seed(conn, content, force=True)


def test_phase_deadline_check(conn, content):
    seed(conn, content)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE team_state SET phase = 'CHALLENGES' WHERE team_id = 'team-1'")


def test_step_must_be_riddle_xor_challenges(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO step (id, location_kind, location_json, code, kind, riddle_text) "
            "VALUES ('x', 'text', '{}', '1', 'challenges', 'oops')"
        )


def test_foreign_keys_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO team (id, name, itinerary_id, join_code) VALUES ('t', 'T', 'nope', 'J')")
