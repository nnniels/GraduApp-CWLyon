"""Organiser view: fail-closed access, login, session independence, the three tabs, CSV."""
import time
from datetime import datetime, timezone

import pytest

from graduapp.db import repo

from .test_game import LAMPS, SECRETS, SING, Player, expire

PASSWORD = "test-password"
ADMIN_URLS = [
    "/admin/", "/admin/teams", "/admin/teams/team-1", "/admin/log", "/admin/codes",
    "/admin/events.csv", "/admin/answers.csv",
]


@pytest.fixture
def admin(app):
    client = app.test_client()
    assert client.post("/admin/login", data={"password": PASSWORD}).status_code == 303
    return client


@pytest.fixture
def me(client, db):
    return Player(client, db)


def text(response) -> str:
    return response.get_data(as_text=True)


# Access

@pytest.mark.parametrize("password", ["", "   ", "change-me"])
def test_no_usable_password_means_no_organiser_view(app, password):
    app.config["ADMIN_PASSWORD"] = password
    client = app.test_client()
    assert client.get("/admin/login").status_code == 404
    for attempt in (password, ""):
        assert client.post("/admin/login", data={"password": attempt}).status_code == 404
    assert client.get("/admin/teams").status_code == 404
    assert "admin" not in text(client.get("/")).lower()  # no link on screen A either


def test_anonymous_gets_nothing(client, db):
    for url in ADMIN_URLS:
        response = client.get(url)
        assert response.status_code == 303 and "/admin/login" in response.headers["Location"], url
        assert not any(s in text(response) for s in SECRETS), url
    assert client.post("/admin/deadline", data={"deadline": "2030-01-01T10:00"}).status_code == 303
    assert repo.get_general_deadline(db) is None


@pytest.mark.parametrize("password", ["", "wrong", PASSWORD + " ", PASSWORD.upper()])
def test_wrong_or_empty_password_is_refused(client, password):
    response = client.post("/admin/login", data={"password": password})
    assert response.status_code == 401
    assert client.get("/admin/teams").status_code == 303


def test_login_then_logout(app):
    client = app.test_client()
    assert client.post("/admin/login", data={"password": PASSWORD}).status_code == 303
    assert client.get("/admin/teams").status_code == 200
    assert client.post("/admin/logout").status_code == 303
    assert client.get("/admin/teams").status_code == 303


def test_login_is_rate_limited_per_client_ip(app):
    client = app.test_client()
    attacker = {"CF-Connecting-IP": "203.0.113.9"}
    for _ in range(5):
        assert client.post("/admin/login", data={"password": "x"}, headers=attacker).status_code == 401
    blocked = client.post("/admin/login", data={"password": PASSWORD}, headers=attacker)
    assert blocked.status_code == 429 and "Too many" in text(blocked)
    other = client.post("/admin/login", data={"password": PASSWORD}, headers={"CF-Connecting-IP": "203.0.113.10"})
    assert other.status_code == 303  # somebody else is not locked out


def test_admin_session_expires(admin):
    with admin.session_transaction() as s:
        s["admin_at"] = int(time.time()) - 9 * 3600
    assert admin.get("/admin/teams").status_code == 303


def test_admin_pages_are_never_cached(admin):
    for url in ADMIN_URLS[1:]:
        assert admin.get(url).headers["Cache-Control"] == "no-store", url


def test_admin_and_team_sessions_do_not_erase_each_other(client, app):
    client.post("/admin/login", data={"password": PASSWORD})
    client.post("/join", data={"team_id": "team-1", "name": "Team 1", "code": "TEAM1-7342"})
    assert client.get("/admin/teams").status_code == 200  # joining a team kept the admin flag
    assert "Start the game" in text(client.get("/"))  # and the team is still there
    client.post("/admin/logout")
    assert "Start the game" in text(client.get("/"))  # logging out kept the team


def test_screen_a_has_a_discreet_link(client):
    assert 'href="/admin/login"' in text(client.get("/"))


# Teams tab

def test_teams_tab_shows_progress_and_the_next_code(me, admin):
    me.start()
    me.arrive("0000")
    html = text(admin.get("/admin/teams"))
    assert "Team 1" in html and "<strong>GOING</strong>" in html and "step 1/3" in html
    assert "Next code: <strong>4821</strong>" in html
    assert 'aria-current="page">Teams' in html
    assert "Wrong codes: 1" in html
    me.arrive("4821")
    me.tick(SING)
    html = text(admin.get("/admin/teams"))
    assert "CHALLENGES" in html and "Challenges ticked: 1/2" in html


def test_viewing_teams_settles_a_timed_out_step(me, admin):
    me.start()
    me.arrive("4821")
    expire(me.db)  # the phone is idle: nobody will ever ask the server
    html = text(admin.get("/admin/teams"))
    assert "1 failed" in html
    assert [e.type for e in repo.load_events(me.db, "team-1")].count("STEP_FAILED") == 1


def test_drill_down_shows_answers_escaped_and_flags_lost_points(me, admin):
    me.start()
    me.arrive("4821")
    me.tick(SING, "<b>we sang</b>")
    expire(me.db)
    me.get("/game/panel")
    me.arrive("1337")
    me.riddle("a map")
    html = text(admin.get("/admin/teams/team-1"))
    assert "&lt;b&gt;we sang&lt;/b&gt;" in html and "<b>we sang</b>" not in html
    assert "no points (failed step)" in html
    assert "a map" in html and "succeeded" in html and "failed" in html
    assert admin.get("/admin/teams/nobody").status_code == 404


# Deadline

def test_deadline_is_entered_in_local_time_and_stored_in_utc(admin, db):
    assert admin.post("/admin/deadline", data={"deadline": "2030-07-01T12:00"}).status_code == 303
    assert repo.get_general_deadline(db) == datetime(2030, 7, 1, 10, 0, tzinfo=timezone.utc)  # Paris, summer
    assert "2030-07-01 12:00:00" in text(admin.get("/admin/teams"))
    admin.post("/admin/deadline", data={"action": "clear"})
    assert repo.get_general_deadline(db) is None


@pytest.mark.parametrize("value", ["", "tomorrow", "2030-13-01T10:00"])
def test_invalid_deadline_is_refused(admin, db, value):
    response = admin.post("/admin/deadline", data={"deadline": value})
    assert response.status_code == 400 and "Invalid date" in text(response)
    assert repo.get_general_deadline(db) is None


# Log and codes

def test_log_is_readable_filterable_and_paged(me, admin, monkeypatch):
    me.start()
    me.arrive("0000")
    me.arrive("4821")
    html = text(admin.get("/admin/log"))
    assert 'wrong code &#34;0000&#34; at Statue of Louis XIV' in html and "arrived at" in html
    assert html.index("arrived at") < html.index("started the game")  # newest first
    assert "started the game" not in text(admin.get("/admin/log?team=team-2"))

    monkeypatch.setattr("graduapp.web.admin.PAGE_SIZE", 3)
    first = text(admin.get("/admin/log"))
    assert "before=" in first and "started the game" not in first
    older = first.split("before=")[1].split('"')[0]
    assert "started the game" in text(admin.get(f"/admin/log?before={older}"))


def test_codes_tab_lists_validation_and_join_codes(admin):
    html = text(admin.get("/admin/codes"))
    for secret in SECRETS:
        assert secret in html


# CSV

def test_events_csv(client, db, admin):
    client.post("/join", data={"team_id": "team-1", "name": "=evil", "code": "TEAM1-7342"})
    response = admin.get("/admin/events.csv")
    body = text(response)
    assert response.mimetype == "text/csv" and body.startswith("\ufeff")
    lines = body.splitlines()
    assert lines[0].endswith("payload") and "renamed" in lines[1] and "joined" in lines[2]  # oldest first
    assert ",'=evil," in body and ",=evil," not in body  # a team name must not run as a formula


def test_answers_csv_neutralises_formulas_and_keeps_accents(me, admin):
    me.start()
    me.arrive("4821")
    me.tick(SING, "=HYPERLINK(\"http://x\")")
    me.tick(LAMPS, "é à ç")
    body = text(admin.get("/admin/answers.csv"))
    assert "\"'=HYPERLINK" in body and "é à ç" in body
    assert body.splitlines()[0].startswith("\ufeffteam_id,team,step,kind")
