import pytest

from graduapp.engine.errors import InvalidTransition
from graduapp.engine.states import Phase, TeamState, unlocked_general
from graduapp.engine.transitions import TickGeneral, UntickGeneral, transition

from .conftest import T0, at


def run(state, course, action, now=T0, deadline=None):
    return transition(state, course, action, now, general_deadline=deadline)


def test_unlocked_general_is_derived_from_progress(course):
    assert unlocked_general(course, TeamState()) == {"g-start"}
    assert unlocked_general(course, TeamState(0, Phase.GOING)) == {"g-start"}
    assert unlocked_general(course, TeamState(0, Phase.CHALLENGES, at(1))) == {"g-start", "g-u1"}
    assert unlocked_general(course, TeamState(1, Phase.GOING)) == {"g-start", "g-u1"}
    assert unlocked_general(course, TeamState(3, Phase.ENDED)) == {"g-start", "g-u1", "g-u2"}


def test_cannot_tick_before_starting(course):
    with pytest.raises(InvalidTransition):
        run(TeamState(), course, TickGeneral("g-start"))


def test_cannot_tick_a_locked_challenge(course, started):
    with pytest.raises(InvalidTransition):
        run(started, course, TickGeneral("g-u1"))


@pytest.mark.parametrize(
    "state",
    [
        TeamState(0, Phase.GOING),
        TeamState(1, Phase.RIDDLE),
        TeamState(3, Phase.ENDED),
    ],
)
def test_tick_and_untick_in_any_started_phase(course, state):
    state, events = run(state, course, TickGeneral("g-start", " proof "))
    assert state.general_ticked == {"g-start"}
    assert events[0].payload == {"scope": "general", "challenge_id": "g-start", "text": "proof"}
    state, _ = run(state, course, UntickGeneral("g-start"))
    assert state.general_ticked == frozenset()


def test_tick_during_timed_phase_keeps_the_phase(course):
    state = TeamState(0, Phase.CHALLENGES, at(600))
    state, _ = run(state, course, TickGeneral("g-start"), now=at(10))
    assert state.phase is Phase.CHALLENGES and state.phase_deadline == at(600)


def test_tick_twice_and_untick_unticked_are_refused(course, started):
    state, _ = run(started, course, TickGeneral("g-start"))
    with pytest.raises(InvalidTransition):
        run(state, course, TickGeneral("g-start"))
    with pytest.raises(InvalidTransition):
        run(started, course, UntickGeneral("g-start"))


def test_general_deadline_closes_ticks_and_unticks(course, started):
    deadline = at(3600)
    state, _ = run(started, course, TickGeneral("g-start"), now=at(3599), deadline=deadline)
    with pytest.raises(InvalidTransition):
        run(started, course, TickGeneral("g-start"), now=at(3600), deadline=deadline)
    with pytest.raises(InvalidTransition):
        run(state, course, UntickGeneral("g-start"), now=at(3600), deadline=deadline)


def test_general_deadline_stays_open_after_the_game_ended(course):
    ended = TeamState(3, Phase.ENDED)
    state, _ = run(ended, course, TickGeneral("g-u2"), now=at(7200), deadline=at(9000))
    assert state.general_ticked == {"g-u2"}


def test_no_deadline_means_no_limit(course, started):
    state, _ = run(started, course, TickGeneral("g-start"), now=at(10**7), deadline=None)
    assert state.general_ticked == {"g-start"}
