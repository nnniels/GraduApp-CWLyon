from datetime import datetime, timezone

from graduapp.db import repo

NOW = datetime(2026, 11, 7, 14, 0, tzinfo=timezone.utc)


def run(app, *args):
    return app.test_cli_runner().invoke(args=["show-events", *args])


def test_no_events(app):
    result = run(app)
    assert result.exit_code == 0 and "No events." in result.output


def test_lists_events_with_team_and_payload(app, db):
    repo.join_team(db, "team-1", "TEAM1-7342", "The Foxes", NOW)
    repo.join_team(db, "team-2", "wrong", "Team 2", NOW)
    out = run(app).output
    assert "TEAM_RENAMED" in out and '"to": "The Foxes"' in out
    assert "TEAM_JOINED" in out and "JOIN_REJECTED" in out
    assert "2026-11-07 14:00:00" in out and "team-2" in out


def test_filter_by_team_and_tail(app, db):
    repo.join_team(db, "team-1", "TEAM1-7342", "The Foxes", NOW)
    repo.join_team(db, "team-2", "wrong", "Team 2", NOW)
    only_team2 = run(app, "--team", "team-2").output
    assert "JOIN_REJECTED" in only_team2 and "TEAM_JOINED" not in only_team2
    last = run(app, "--tail", "1").output
    assert "JOIN_REJECTED" in last and "TEAM_RENAMED" not in last
