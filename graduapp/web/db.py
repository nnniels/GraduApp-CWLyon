"""One SQLite connection per request (connections cannot be shared between threads)."""
from flask import Flask, current_app, g

from ..db.connection import connect, init_db


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app: Flask) -> None:
    # Idempotent: a fresh deployment must not crash before `flask seed` has run.
    conn = connect(app.config["DATABASE_PATH"])
    init_db(conn)
    conn.close()
    app.teardown_appcontext(close_db)
