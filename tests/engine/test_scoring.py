import ast
from datetime import timedelta
from pathlib import Path

import graduapp.engine as engine_pkg
from graduapp.engine.events import EventType as E
from graduapp.engine.scoring import compute_score
from graduapp.engine.states import TeamState
from graduapp.engine.transitions import (
    Arrive,
    Start,
    SubmitRiddle,
    TickGeneral,
    TickStep,
    UntickGeneral,
    resolve_expiry,
    transition,
)

from .conftest import at


class Game:
    """Drives the engine and keeps the event log, like the db layer will."""

    def __init__(self, course):
        self.course, self.state, self.events = course, TeamState(), []

    def do(self, action, seconds):
        self.state, new = transition(self.state, self.course, action, at(seconds))
        self.events += new
        return self

    def expire(self, seconds):
        self.state, new = resolve_expiry(self.state, self.course, at(seconds))
        self.events += new
        return self

    def score(self):
        return compute_score(self.events, self.course)


def test_full_game_with_one_failure(course):
    g = Game(course)
    g.do(Start(), 0)
    g.do(TickGeneral("g-start"), 5)                 # +1
    g.do(Arrive(0, "4821"), 60)
    g.do(TickStep(0, "c1"), 100)
    g.do(TickStep(0, "c2"), 120)                    # success: 2 + 3 + step bonus 2
    g.do(Arrive(1, "1337"), 300)
    g.do(SubmitRiddle(1, "a map"), 330)             # success, no points
    g.do(Arrive(2, "0420"), 400)                    # timed 60 s, nothing ticked
    g.expire(500)                                   # failure, c4 would have been 5
    assert g.state.step_index == 3
    s = g.score()
    assert (s.general, s.steps, s.total) == (1, 7, 8)
    assert (s.steps_succeeded, s.steps_failed) == (2, 1)
    assert s.duration == timedelta(seconds=460)  # failure is stamped with its deadline (400 + 60)


def test_failed_step_scores_nothing_even_with_ticks(course):
    g = Game(course)
    g.do(Start(), 0).do(Arrive(0, "4821"), 1).do(TickStep(0, "c1"), 2).expire(700)
    s = g.score()
    assert (s.total, s.steps_failed) == (0, 1)


def test_unticked_general_challenge_does_not_score(course):
    g = Game(course)
    g.do(Start(), 0).do(TickGeneral("g-start"), 1).do(UntickGeneral("g-start"), 2)
    assert g.score().total == 0


def test_duration_is_none_until_the_game_ends(course):
    g = Game(course).do(Start(), 0)
    assert g.score().duration is None


def test_event_payloads_are_json_serialisable(course):
    import json

    g = Game(course)
    g.do(Start(), 0).do(Arrive(0, "4821"), 1).do(TickStep(0, "c1", "x"), 2)
    for e in g.events:
        json.dumps(e.payload)


def test_engine_is_pure():
    """The engine must not import Flask, sqlite3, or any other layer of the app."""
    forbidden = {"flask", "sqlite3", "yaml", "graduapp.db", "graduapp.web", "graduapp.content"}
    for path in Path(engine_pkg.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level <= 1, f"{path.name} imports outside the engine"
                modules = [node.module or ""] if node.level == 0 else []
            else:
                continue
            for m in modules:
                assert not any(m == f or m.startswith(f + ".") for f in forbidden), (path.name, m)
