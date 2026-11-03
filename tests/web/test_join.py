import pytest

from graduapp import create_app
from graduapp.db import repo

TEAM1 = {"team_id": "team-1", "name": "Team 1", "code": "TEAM1-7342"}


def join(client, **overrides):
    return client.post("/join", data={**TEAM1, **overrides})


def event_types(db, team_id="team-1"):
    return [e.type for e in repo.load_events(db, team_id)]


def session_team(client):
    with client.session_transaction() as s:
        return s.get("team_id")


# Screen A

def test_screen_a_lists_teams_without_codes(client):
    html = client.get("/").get_data(as_text=True)
    assert "Team 1" in html and "Team 2" in html
    assert "TEAM1-7342" not in html and "TEAM2-9051" not in html


def test_screen_a_without_seed_shows_a_hint(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "k", "DATABASE_PATH": str(tmp_path / "empty.sqlite")})
    assert "flask seed" in app.test_client().get("/").get_data(as_text=True)


# Joining

def test_right_code_logs_in_and_locks(client, db):
    response = join(client)
    assert response.status_code == 303 and response.headers["Location"] == "/"
    assert session_team(client) == "team-1"
    assert event_types(db) == ["TEAM_JOINED"]
    assert "Team 1" in client.get("/").get_data(as_text=True)
    assert "Choose your team" not in client.get("/").get_data(as_text=True)


def test_code_ignores_case_and_spaces(client):
    assert join(client, code="  team1-7342 ").status_code == 303


def test_wrong_code_is_refused_and_logged(client, db):
    response = join(client, code="nope", name="Hacked")
    assert response.status_code == 403
    assert "Wrong code" in response.get_data(as_text=True)
    assert session_team(client) is None
    assert event_types(db) == ["JOIN_REJECTED"]
    assert repo.get_team(db, "team-1").name == "Team 1"  # not renamed without the code


def test_rename_on_join(client, db):
    join(client, name="  The   Foxes ")
    assert repo.get_team(db, "team-1").name == "The Foxes"
    assert event_types(db) == ["TEAM_RENAMED", "TEAM_JOINED"]
    renamed = repo.load_events(db, "team-1")[0]
    assert renamed.payload == {"from": "Team 1", "to": "The Foxes"}


def test_blank_name_keeps_the_current_name(client, db):
    join(client, name="   ")
    assert repo.get_team(db, "team-1").name == "Team 1"
    assert event_types(db) == ["TEAM_JOINED"]


def test_name_is_escaped_on_screen(client):
    join(client, name="<b>x</b>")
    assert "<b>x</b>" not in client.get("/").get_data(as_text=True)


def test_unknown_team(client):
    assert join(client, team_id="nope").status_code == 400
    assert session_team(client) is None


@pytest.mark.parametrize("code", ["TEAM1-7342", "wrong"])
def test_bad_name_is_refused_whatever_the_code(client, db, code):
    # Same answer for a right and a wrong code: no oracle that skips the rate limit.
    response = join(client, name="x" * 41, code=code)
    assert response.status_code == 400
    assert session_team(client) is None
    assert event_types(db) == []


def test_stale_cookie_for_a_missing_team_is_dropped(client):
    with client.session_transaction() as s:
        s["team_id"] = "ghost"
    assert "Choose your team" in client.get("/").get_data(as_text=True)
    assert session_team(client) is None


def test_switching_team_needs_the_other_teams_code(client):
    join(client)
    assert join(client, team_id="team-2", name="Team 2", code=TEAM1["code"]).status_code == 403
    assert session_team(client) == "team-1"
    assert join(client, team_id="team-2", name="Team 2", code="TEAM2-9051").status_code == 303
    assert session_team(client) == "team-2"


# Cookie

def test_cookie_is_httponly_lax_and_lasts(client):
    cookie = join(client).headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert "Expires=" in cookie  # permanent: survives closing the browser


def test_cookie_secure_flag_is_configurable(db_path):
    app = create_app(
        {"TESTING": True, "SECRET_KEY": "k", "DATABASE_PATH": db_path, "SESSION_COOKIE_SECURE": True}
    )
    cookie = join(app.test_client()).headers["Set-Cookie"]
    assert "Secure" in cookie


def test_secret_key_is_mandatory_outside_debug(db_path):
    for bad in ("", "change-me"):  # unset, and the placeholder from .env.example
        with pytest.raises(RuntimeError):
            create_app({"SECRET_KEY": bad, "DATABASE_PATH": db_path})
    assert create_app({"SECRET_KEY": "", "DATABASE_PATH": db_path, "TESTING": True})


# Rate limit

def test_ten_wrong_codes_lock_the_team_even_for_the_right_code(client, db):
    for _ in range(10):
        assert join(client, code="nope").status_code == 403
    response = join(client)  # right code, but locked out
    assert response.status_code == 429
    assert "Too many" in response.get_data(as_text=True)
    assert session_team(client) is None
    assert event_types(db).count("JOIN_REJECTED") == 10  # the locked attempt never reached the repo


def test_lockout_is_per_team(client):
    for _ in range(10):
        join(client, code="nope")
    assert join(client, team_id="team-2", name="Team 2", code="TEAM2-9051").status_code == 303


def test_successful_joins_do_not_use_attempts(client):
    for _ in range(15):
        assert join(client).status_code == 303


def test_invalid_names_do_not_use_attempts(client):
    for _ in range(15):
        assert join(client, name="x" * 41, code="nope").status_code == 400
    assert join(client).status_code == 303
