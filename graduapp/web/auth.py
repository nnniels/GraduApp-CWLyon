"""Team cookie and organiser session (both in Flask's signed session), and the rate limits."""
import hmac
import time

from flask import current_app, request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from ..db import repo

# Behind the Cloudflare tunnel every request comes from 127.0.0.1, so a per-IP key would lock
# everybody out after 10 attempts. The counter is per team instead: it needs no IP at all.
# Trade-off: someone can burn a team's attempts. Acceptable for a friendly game.
limiter = Limiter(key_func=get_remote_address)

TEAM_KEYS = ("team_id", "view")  # the team's part of the session: the admin flag is kept apart
ADMIN_KEY = "admin_at"
PLACEHOLDER_PASSWORD = "change-me"


def join_key() -> str:
    return "join:" + request.form.get("team_id", "")[:64]


def client_ip() -> str:
    """The real client behind the tunnel.

    CF-Connecting-IP is only believed when the request comes from this machine (the tunnel):
    Cloudflare overwrites that header, but a direct connection could forge it.
    """
    if request.remote_addr in ("127.0.0.1", "::1"):
        forwarded = request.headers.get("CF-Connecting-IP", "").strip()
        if forwarded:
            return forwarded
    return get_remote_address()


# Team

def login(team_id: str) -> None:
    for key in TEAM_KEYS:
        session.pop(key, None)
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
        for key in TEAM_KEYS:
            session.pop(key, None)
        return None


# Organiser

def admin_enabled() -> bool:
    """Fail closed: no password, or the placeholder, means there is no organiser view at all."""
    password = current_app.config["ADMIN_PASSWORD"]
    return bool(password.strip()) and password != PLACEHOLDER_PASSWORD


def check_admin_password(candidate: str) -> bool:
    if not admin_enabled() or not candidate:
        return False
    return hmac.compare_digest(
        candidate.encode(), current_app.config["ADMIN_PASSWORD"].encode()
    )


def admin_login() -> None:
    session[ADMIN_KEY] = int(time.time())
    session.permanent = True


def admin_logout() -> None:
    session.pop(ADMIN_KEY, None)


def admin_logged_in() -> bool:
    """The cookie itself lives 2 days (it carries the team): the admin flag expires sooner."""
    logged_at = session.get(ADMIN_KEY)
    if not isinstance(logged_at, int):
        return False
    age = time.time() - logged_at
    return 0 <= age < current_app.config["ADMIN_SESSION_LIFETIME"].total_seconds()
