from datetime import datetime, timedelta, timezone

import pytest

from graduapp.engine.states import Course, Phase, StepDef, TeamState

T0 = datetime(2026, 11, 7, 14, 0, tzinfo=timezone.utc)


def at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


@pytest.fixture
def course() -> Course:
    """s1: timed, 2 of 3 in 600 s. s2: riddle. s3: timed, 1 of 1 in 60 s."""
    return Course(
        steps=(
            StepDef("s1", "4821", "challenges", points=2, unlocks=("g-u1",),
                    challenge_ids=("c1", "c2", "c3"), k=2, duration_s=600),
            StepDef("s2", "1337", "riddle", unlocks=("g-u2", "g-start")),
            StepDef("s3", "0420", "challenges", challenge_ids=("c4",), k=1, duration_s=60),
        ),
        general_at_start=frozenset({"g-start"}),
        points={"c1": 2, "c2": 3, "c3": 1, "c4": 5, "g-start": 1, "g-u1": 2, "g-u2": 4},
    )


@pytest.fixture
def started() -> TeamState:
    return TeamState(step_index=0, phase=Phase.GOING)
