"""Team cookie (Flask's signed session) and the join rate limit."""
from flask import request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from ..db import repo

# Behind the Cloudflare tunnel every request comes from 127.0.0.1, so a per-IP key would lock
# everybody out after 10 attempts. The counter is per team instead: it needs no IP at all.
# Trade-off: someone can burn a team's attempts. Acceptable for a friendly game.
limiter = Limiter(key_func=get_remote_address)


def join_key() -> str:
    return "join:" + request.form.get("team_id", "")[:64]


def login(team_id: str) -> None:
    session.clear()
    session["team_id"] = team_id
    session.permanent = True


def current_team(conn) -> repo.TeamInfo | None:
    """The team of this phone, or None. A cookie for a team that no longer exists is dropped."""
    team_id = session.get("team_id")
    if not team_id:
        return None
    try:
        return repo.get_team(conn, team_id)
    except repo.UnknownTeam:
        session.clear()
        return None
