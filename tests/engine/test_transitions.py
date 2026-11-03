import pytest

from graduapp.engine.errors import InvalidTransition
from graduapp.engine.events import EventType as E
from graduapp.engine.states import Phase, TeamState
from graduapp.engine.transitions import (
    Arrive,
    Start,
    SubmitRiddle,
    TickStep,
    UntickStep,
    resolve_expiry,
    transition,
)

from .conftest import T0, at


def types(events):
    return [e.type for e in events]


def run(state, course, action, now=T0, **kw):
    return transition(state, course, action, now, **kw)


def test_start(course):
    state, events = run(TeamState(), course, Start())
    assert (state.phase, state.step_index) == (Phase.GOING, 0)
    assert types(events) == [E.GAME_STARTED]


def test_start_twice_is_refused(course, started):
    with pytest.raises(InvalidTransition):
        run(started, course, Start())


def test_wrong_code_changes_nothing_and_is_logged(course, started):
    state, events = run(started, course, Arrive(0, "nope"))
    assert state == started
    assert types(events) == [E.CODE_REJECTED]
    assert events[0].payload["code"] == "nope"


def test_code_ignores_case_and_spaces(course, started):
    state, _ = run(started, course, Arrive(0, "  4821 "))
    assert state.phase is Phase.CHALLENGES


def test_arrive_at_timed_step_sets_deadline_and_unlocks(course, started):
    state, events = run(started, course, Arrive(0, "4821"))
    assert state.phase is Phase.CHALLENGES
    assert state.phase_deadline == at(600)
    assert types(events) == [E.ARRIVED, E.CHALLENGES_UNLOCKED, E.CHALLENGE_PHASE_STARTED]
    assert events[1].payload["challenge_ids"] == ["g-u1"]


def test_arrive_at_riddle_step_has_no_deadline(course):
    state = TeamState(step_index=1, phase=Phase.GOING)
    state, events = run(state, course, Arrive(1, "1337"))
    assert (state.phase, state.phase_deadline) == (Phase.RIDDLE, None)
    # g-start was already unlocked, so only g-u2 is announced as new
    assert events[1].payload["challenge_ids"] == ["g-u2"]


def test_double_arrive_is_refused(course, started):
    state, _ = run(started, course, Arrive(0, "4821"))
    with pytest.raises(InvalidTransition):
        run(state, course, Arrive(0, "4821"))


def test_stale_step_index_is_refused(course, started):
    with pytest.raises(InvalidTransition):
        run(started, course, Arrive(1, "1337"))


def test_reaching_k_succeeds_and_advances(course, started):
    state, _ = run(started, course, Arrive(0, "4821"))
    state, _ = run(state, course, TickStep(0, "c1", "done"), now=at(10))
    assert state.phase is Phase.CHALLENGES
    state, events = run(state, course, TickStep(0, "c2"), now=at(20))
    assert (state.phase, state.step_index) == (Phase.GOING, 1)
    assert state.step_ticked == frozenset() and state.phase_deadline is None
    assert types(events) == [E.CHALLENGE_TICKED, E.STEP_SUCCEEDED]
    assert events[1].payload["challenge_ids"] == ["c1", "c2"]


def test_untick_then_tick_again(course, started):
    state, _ = run(started, course, Arrive(0, "4821"))
    state, _ = run(state, course, TickStep(0, "c1"), now=at(5))
    state, events = run(state, course, UntickStep(0, "c1"), now=at(6))
    assert state.step_ticked == frozenset() and types(events) == [E.CHALLENGE_UNTICKED]
    state, _ = run(state, course, TickStep(0, "c1"), now=at(7))
    assert state.step_ticked == {"c1"}


def test_tick_errors(course, started):
    state, _ = run(started, course, Arrive(0, "4821"))
    state, _ = run(state, course, TickStep(0, "c1"), now=at(5))
    for action in (TickStep(0, "c1"), TickStep(0, "c4"), UntickStep(0, "c2")):
        with pytest.raises(InvalidTransition):
            run(state, course, action, now=at(6))


def test_tick_outside_challenge_phase_is_refused(course, started):
    with pytest.raises(InvalidTransition):
        run(started, course, TickStep(0, "c1"))


def test_riddle_answer_advances(course):
    state = TeamState(step_index=1, phase=Phase.RIDDLE)
    state, events = run(state, course, SubmitRiddle(1, "  a map "))
    assert (state.phase, state.step_index) == (Phase.GOING, 2)
    assert types(events) == [E.RIDDLE_ANSWERED, E.STEP_SUCCEEDED]
    assert events[0].payload["text"] == "a map"


def test_empty_riddle_answer_is_refused(course):
    state = TeamState(step_index=1, phase=Phase.RIDDLE)
    with pytest.raises(InvalidTransition):
        run(state, course, SubmitRiddle(1, "   "))


def test_last_step_ends_the_game(course):
    state = TeamState(step_index=2, phase=Phase.GOING)
    state, _ = run(state, course, Arrive(2, "0420"))
    state, events = run(state, course, TickStep(2, "c4"), now=at(10))
    assert (state.phase, state.step_index) == (Phase.ENDED, 3)
    assert types(events) == [E.CHALLENGE_TICKED, E.STEP_SUCCEEDED, E.GAME_ENDED]


def test_no_action_after_the_end(course):
    state = TeamState(step_index=3, phase=Phase.ENDED)
    with pytest.raises(InvalidTransition):
        run(state, course, Arrive(3, "x"))


# Lazy expiry


def timed_state(course, started):
    state, _ = run(started, course, Arrive(0, "4821"))
    state, _ = run(state, course, TickStep(0, "c1"), now=at(5))
    return state  # deadline at(600), one challenge ticked


def test_resolve_expiry_before_deadline_does_nothing(course, started):
    state = timed_state(course, started)
    assert resolve_expiry(state, course, at(599)) == (state, [])


def test_expiry_fails_the_step_and_advances(course, started):
    state, events = resolve_expiry(timed_state(course, started), course, at(900))
    assert (state.phase, state.step_index) == (Phase.GOING, 1)
    assert types(events) == [E.STEP_FAILED]
    assert events[0].payload["challenge_ids"] == ["c1"]
    assert events[0].ts == at(600)  # stamped with the deadline, not with the late request


def test_deadline_is_exclusive(course, started):
    state, events = resolve_expiry(timed_state(course, started), course, at(600))
    assert types(events) == [E.STEP_FAILED]


def test_expiry_on_last_step_ends_the_game(course):
    state = TeamState(step_index=2, phase=Phase.GOING)
    state, _ = run(state, course, Arrive(2, "0420"))
    state, events = resolve_expiry(state, course, at(61))
    assert state.phase is Phase.ENDED
    assert types(events) == [E.STEP_FAILED, E.GAME_ENDED]


def test_late_tick_is_refused_but_expiry_is_kept(course, started):
    state = timed_state(course, started)
    with pytest.raises(InvalidTransition) as exc:
        run(state, course, TickStep(0, "c2"), now=at(700))
    assert (exc.value.state.phase, exc.value.state.step_index) == (Phase.GOING, 1)
    assert types(exc.value.events) == [E.STEP_FAILED]


def test_expiry_then_action_on_next_step_in_one_call(course, started):
    state = timed_state(course, started)
    state, events = run(state, course, Arrive(1, "1337"), now=at(700))
    assert state.phase is Phase.RIDDLE
    assert types(events)[0] == E.STEP_FAILED


def test_failed_step_still_unlocks_what_it_unlocked_on_arrival(course, started):
    state, _ = run(started, course, Arrive(0, "4821"))
    state, _ = resolve_expiry(state, course, at(601))
    from graduapp.engine.states import unlocked_general

    assert "g-u1" in unlocked_general(course, state)
