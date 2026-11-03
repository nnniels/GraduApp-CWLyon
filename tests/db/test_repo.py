from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from graduapp.content.loader import load_content
from graduapp.db import repo
from graduapp.db.connection import connect, init_db
from graduapp.db.seed import seed
from graduapp.engine.errors import InvalidTransition
from graduapp.engine.events import EventType as E
from graduapp.engine.states import Phase
from graduapp.engine.transitions import (
    Arrive,
    Start,
    SubmitRiddle,
    TickGeneral,
    TickStep,
    UntickStep,
)

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"
T0 = datetime(2026, 11, 7, 14, 0, tzinfo=timezone.utc)
TEAM = "team-1"  # itinerary-a: place-bellecour (k=2 of 3, 600 s), tour-metallique, place-terreaux


def at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    seed(c, load_content(CONTENT_DIR))
    return c


def act(conn, action, seconds=0, team=TEAM):
    return repo.apply_action(conn, team, action, at(seconds))


def types(conn, team=TEAM):
    return [e.type for e in repo.load_events(conn, team)]


def rows(conn, sql, *args):
    return [tuple(r) for r in conn.execute(sql, args)]


# Loading

def test_load_course(conn):
    course = repo.load_course(conn, "itinerary-a")
    assert [s.id for s in course.steps] == ["place-bellecour", "tour-metallique", "place-terreaux"]
    first = course.steps[0]
    assert (first.kind, first.k, first.duration_s) == ("challenges", 2, 600)
    assert first.unlocks == ("selfie-statue",)
    assert len(first.challenge_ids) == 3
    assert course.general_at_start == {"team-photo", "street-musician"}
    assert course.points["bellecour-human-pyramid"] == 2
    assert course.steps[1].kind == "riddle"


def test_shared_steps_have_their_own_order(conn):
    course = repo.load_course(conn, "itinerary-b")
    assert [s.id for s in course.steps][0] == "place-terreaux"


def test_initial_view(conn):
    view = repo.get_view(conn, TEAM)
    assert view.state.phase is Phase.NOT_STARTED
    assert view.team.name == "Team 1"


def test_unknown_team(conn):
    with pytest.raises(repo.UnknownTeam):
        repo.get_view(conn, "nope")
    with pytest.raises(repo.UnknownTeam):
        act(conn, Start(), team="nope")


# Actions and persistence

def test_state_survives_a_reload(conn):
    act(conn, Start(), 0)
    act(conn, Arrive(0, "4821"), 10)
    act(conn, TickStep(0, "bellecour-sing", "off key"), 20)
    state = repo.get_view(conn, TEAM).state
    assert state.phase is Phase.CHALLENGES
    assert state.phase_deadline == at(610)
    assert state.step_ticked == {"bellecour-sing"}


def test_events_are_logged_in_order(conn):
    act(conn, Start(), 0)
    act(conn, Arrive(0, "4821"), 10)
    assert types(conn) == [E.GAME_STARTED, E.ARRIVED, E.CHALLENGES_UNLOCKED, E.CHALLENGE_PHASE_STARTED]


def test_wrong_code_is_logged_and_changes_nothing(conn):
    act(conn, Start(), 0)
    applied = act(conn, Arrive(0, "0000"), 5)
    assert applied.state.phase is Phase.GOING
    assert types(conn)[-1] == E.CODE_REJECTED


def test_refused_action_writes_nothing(conn):
    with pytest.raises(InvalidTransition):
        act(conn, Arrive(0, "4821"))  # not started
    assert types(conn) == []


def test_completion_rows_follow_ticks_and_unticks(conn):
    act(conn, Start(), 0)
    act(conn, Arrive(0, "4821"), 1)
    act(conn, TickStep(0, "bellecour-sing", "x"), 2)
    assert rows(conn, "SELECT challenge_id, text FROM challenge_completion") == [("bellecour-sing", "x")]
    act(conn, UntickStep(0, "bellecour-sing"), 3)
    assert rows(conn, "SELECT * FROM challenge_completion") == []


def test_general_ticks_are_stored_and_reloaded(conn):
    act(conn, Start(), 0)
    act(conn, TickGeneral("team-photo", "with a baker"), 1)
    assert repo.get_view(conn, TEAM).state.general_ticked == {"team-photo"}


def test_closed_step_ticks_stay_in_history_but_not_in_state(conn):
    act(conn, Start(), 0)
    act(conn, Arrive(0, "4821"), 1)
    act(conn, TickStep(0, "bellecour-sing"), 2)
    act(conn, TickStep(0, "bellecour-count-lamps"), 3)  # k = 2: step succeeds
    state = repo.get_view(conn, TEAM).state
    assert (state.phase, state.step_index, state.step_ticked) == (Phase.GOING, 1, frozenset())
    assert len(rows(conn, "SELECT * FROM challenge_completion")) == 2


def test_teams_are_independent(conn):
    act(conn, Start(), 0, team="team-1")
    assert repo.get_view(conn, "team-2").state.phase is Phase.NOT_STARTED
    assert types(conn, "team-2") == []


# Expiry

def test_page_load_persists_expiry(conn):
    act(conn, Start(), 0)
    act(conn, Arrive(0, "4821"), 10)
    applied = repo.resolve_team(conn, TEAM, at(700))
    assert [e.type for e in applied.events] == [E.STEP_FAILED]
    state = repo.get_view(conn, TEAM).state
    assert (state.phase, state.step_index) == (Phase.GOING, 1)
    assert repo.resolve_team(conn, TEAM, at(701)).events == []  # idempotent


def test_expiry_is_saved_even_when_the_late_action_is_refused(conn):
    act(conn, Start(), 0)
    act(conn, Arrive(0, "4821"), 10)
    with pytest.raises(InvalidTransition):
        act(conn, TickStep(0, "bellecour-sing"), 900)
    assert types(conn)[-1] == E.STEP_FAILED
    assert repo.get_view(conn, TEAM).state.step_index == 1


# Score

def test_score_from_the_log(conn):
    act(conn, Start(), 0)
    act(conn, TickGeneral("team-photo"), 1)                   # +1
    act(conn, Arrive(0, "4821"), 10)
    act(conn, TickStep(0, "bellecour-human-pyramid"), 20)     # 2
    act(conn, TickStep(0, "bellecour-sing"), 30)              # 1, +2 step bonus
    act(conn, Arrive(1, "1337"), 40)
    act(conn, SubmitRiddle(1, "a map"), 50)
    act(conn, Arrive(2, "0420"), 60)
    act(conn, SubmitRiddle(2, "Bartholdi"), 70)
    score = repo.get_score(conn, TEAM)
    assert (score.general, score.steps, score.total) == (1, 5, 6)
    assert score.duration == timedelta(seconds=70)
    assert repo.get_view(conn, TEAM).state.phase is Phase.ENDED


# Concurrency

def test_simultaneous_double_tap_applies_once(tmp_path):
    import threading

    path = str(tmp_path / "game.sqlite")
    setup = connect(path)
    init_db(setup)
    seed(setup, load_content(CONTENT_DIR))
    repo.apply_action(setup, TEAM, Start(), at(0))

    outcomes = []
    barrier = threading.Barrier(2)

    def tap():
        c = connect(path)
        barrier.wait()
        try:
            repo.apply_action(c, TEAM, Arrive(0, "4821"), at(10))
            outcomes.append("applied")
        except InvalidTransition:
            outcomes.append("refused")
        finally:
            c.close()

    threads = [threading.Thread(target=tap) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert sorted(outcomes) == ["applied", "refused"]
    assert [e.type for e in repo.load_events(setup, TEAM)].count(E.ARRIVED) == 1


# General deadline

def test_general_deadline_roundtrip(conn):
    assert repo.get_general_deadline(conn) is None
    repo.set_general_deadline(conn, at(3600))
    assert repo.get_general_deadline(conn) == at(3600)
    repo.set_general_deadline(conn, None)
    assert repo.get_general_deadline(conn) is None


def test_general_deadline_is_enforced(conn):
    act(conn, Start(), 0)
    repo.set_general_deadline(conn, at(100))
    act(conn, TickGeneral("team-photo"), 99)
    with pytest.raises(InvalidTransition):
        act(conn, TickGeneral("street-musician"), 100)


def test_naive_datetimes_are_rejected(conn):
    with pytest.raises(ValueError):
        repo.set_general_deadline(conn, datetime(2026, 11, 7, 14, 0))


# Teams

def test_join_code(conn):
    assert repo.check_join_code(conn, TEAM, "TEAM1-7342")
    assert repo.check_join_code(conn, TEAM, "  team1-7342 ")
    assert not repo.check_join_code(conn, TEAM, "TEAM2-9051")
    assert not repo.check_join_code(conn, TEAM, "")


def test_team_listing_does_not_expose_codes(conn):
    teams = repo.list_teams(conn)
    assert [t.id for t in teams] == ["team-1", "team-2"]
    assert not hasattr(teams[0], "join_code")


def test_rename_team(conn):
    repo.rename_team(conn, TEAM, "  The   Foxes ")
    assert repo.get_team(conn, TEAM).name == "The Foxes"
    for bad in ("", "   ", "x" * 41):
        with pytest.raises(ValueError):
            repo.rename_team(conn, TEAM, bad)
    with pytest.raises(repo.UnknownTeam):
        repo.rename_team(conn, "nope", "Ghosts")
