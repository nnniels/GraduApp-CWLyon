from pathlib import Path

import pytest

from graduapp import create_app
from graduapp.content.loader import load_content
from graduapp.db.connection import connect, init_db
from graduapp.db.seed import seed
from graduapp.web.auth import limiter

CONTENT_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "content"


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "game.sqlite")
    conn = connect(path)
    init_db(conn)
    seed(conn, load_content(CONTENT_DIR))
    conn.close()
    return path


@pytest.fixture
def app(db_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-key",
            "DATABASE_PATH": db_path,
            "CONTENT_DIR": str(CONTENT_DIR),  # for `flask reset-game --names`
            "ADMIN_PASSWORD": "test-password",
        }
    )
    limiter.reset()  # the limiter is module-level: start every test with empty counters
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(db_path):
    conn = connect(db_path)
    yield conn
    conn.close()
