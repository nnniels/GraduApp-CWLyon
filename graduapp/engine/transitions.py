"""The state machine. See Docs/state_machine.md.

    transition(state, course, action, now, general_deadline) -> (new_state, events)

Pure: no I/O, `now` is injected. Expected outcomes (a wrong code) are returned as events.
Impossible actions raise InvalidTransition, which carries any expiry already resolved.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .errors import InvalidTransition
from .events import Event, EventType
from .states import Course, Phase, StepDef, TeamState, unlocked_general

# Actions. Those bound to a step carry the step_index the client was looking at,
# so a stale screen or a double tap is refused instead of skipping a step.


@dataclass(frozen=True)
class Start:
    pass


@dataclass(frozen=True)
class Arrive:
    step_index: int
    code: str


@dataclass(frozen=True)
class SubmitRiddle:
    step_index: int
    text: str


@dataclass(frozen=True)
class TickStep:
    step_index: int
    challenge_id: str
    text: str = ""


@dataclass(frozen=True)
class UntickStep:
    step_index: int
    challenge_id: str


@dataclass(frozen=True)
class TickGeneral:
    challenge_id: str
    text: str = ""


@dataclass(frozen=True)
class UntickGeneral:
    challenge_id: str


Action = Start | Arrive | SubmitRiddle | TickStep | UntickStep | TickGeneral | UntickGeneral

_STARTED = (Phase.GOING, Phase.RIDDLE, Phase.CHALLENGES, Phase.ENDED)


def _norm(code: str) -> str:
    return code.strip().casefold()


def _step_payload(state: TeamState, step: StepDef) -> dict:
    return {"step_index": state.step_index, "step_id": step.id}


def _advance(state: TeamState, course: Course, now: datetime) -> tuple[TeamState, list[Event]]:
    """Close the current step and move on. Does not log success or failure itself."""
    next_index = state.step_index + 1
    if next_index >= len(course.steps):
        ended = replace(
            state,
            step_index=len(course.steps),
            phase=Phase.ENDED,
            phase_deadline=None,
            step_ticked=frozenset(),
        )
        return ended, [Event(EventType.GAME_ENDED, {}, now)]
    going = replace(
        state,
        step_index=next_index,
        phase=Phase.GOING,
        phase_deadline=None,
        step_ticked=frozenset(),
    )
    return going, []


def resolve_expiry(
    state: TeamState, course: Course, now: datetime
) -> tuple[TeamState, list[Event]]:
    """Lazy expiry: close a timed step whose deadline has passed. Called by every transition.

    Events are stamped with the deadline, the moment the failure really happened.
    """
    if state.phase is not Phase.CHALLENGES or now < state.phase_deadline:
        return state, []
    at = state.phase_deadline
    step = course.steps[state.step_index]
    failed = Event(
        EventType.STEP_FAILED,
        {**_step_payload(state, step), "challenge_ids": sorted(state.step_ticked)},
        at,
    )
    new_state, more = _advance(state, course, at)
    return new_state, [failed, *more]


def transition(
    state: TeamState,
    course: Course,
    action: Action,
    now: datetime,
    general_deadline: datetime | None = None,
) -> tuple[TeamState, list[Event]]:
    """Apply an action. `general_deadline` (None = no limit) closes general challenges."""
    state, events = resolve_expiry(state, course, now)
    try:
        state, new_events = _apply(state, course, action, now, general_deadline)
    except InvalidTransition as exc:
        raise InvalidTransition(str(exc), state=state, events=events) from None
    return state, events + new_events


def _require_step(state: TeamState, step_index: int) -> None:
    if step_index != state.step_index:
        raise InvalidTransition("Stale screen: the team has moved on")


def _require_phase(state: TeamState, *phases: Phase) -> None:
    if state.phase not in phases:
        raise InvalidTransition(f"Not allowed during phase {state.phase.value}")


def _apply(
    state: TeamState,
    course: Course,
    action: Action,
    now: datetime,
    general_deadline: datetime | None,
) -> tuple[TeamState, list[Event]]:
    match action:
        case Start():
            _require_phase(state, Phase.NOT_STARTED)
            started = replace(state, step_index=0, phase=Phase.GOING)
            return started, [Event(EventType.GAME_STARTED, {}, now)]

        case Arrive():
            _require_step(state, action.step_index)
            _require_phase(state, Phase.GOING)
            step = course.steps[state.step_index]
            base = _step_payload(state, step)
            if _norm(action.code) != _norm(step.code):
                return state, [Event(EventType.CODE_REJECTED, {**base, "code": action.code}, now)]

            events = [Event(EventType.ARRIVED, base, now)]
            already = unlocked_general(course, state)
            new_unlocks = [c for c in step.unlocks if c not in already]
            if new_unlocks:
                events.append(
                    Event(EventType.CHALLENGES_UNLOCKED, {**base, "challenge_ids": new_unlocks}, now)
                )
            if step.kind == "riddle":
                return replace(state, phase=Phase.RIDDLE), events
            deadline = now + timedelta(seconds=step.duration_s)
            events.append(
                Event(
                    EventType.CHALLENGE_PHASE_STARTED,
                    {**base, "k": step.k, "deadline": deadline.isoformat()},
                    now,
                )
            )
            return replace(state, phase=Phase.CHALLENGES, phase_deadline=deadline), events

        case SubmitRiddle():
            _require_step(state, action.step_index)
            _require_phase(state, Phase.RIDDLE)
            text = action.text.strip()
            if not text:
                raise InvalidTransition("The answer is empty")
            step = course.steps[state.step_index]
            base = _step_payload(state, step)
            events = [
                Event(EventType.RIDDLE_ANSWERED, {**base, "text": text}, now),
                Event(EventType.STEP_SUCCEEDED, {**base, "challenge_ids": []}, now),
            ]
            new_state, more = _advance(state, course, now)
            return new_state, events + more

        case TickStep():
            _require_step(state, action.step_index)
            _require_phase(state, Phase.CHALLENGES)
            step = course.steps[state.step_index]
            if action.challenge_id not in step.challenge_ids:
                raise InvalidTransition("Unknown challenge for this step")
            if action.challenge_id in state.step_ticked:
                raise InvalidTransition("Challenge already ticked")
            ticked = state.step_ticked | {action.challenge_id}
            base = _step_payload(state, step)
            events = [
                Event(
                    EventType.CHALLENGE_TICKED,
                    {
                        **base,
                        "scope": "step",
                        "challenge_id": action.challenge_id,
                        "text": action.text.strip(),
                    },
                    now,
                )
            ]
            state = replace(state, step_ticked=ticked)
            if len(ticked) < step.k:
                return state, events
            events.append(
                Event(EventType.STEP_SUCCEEDED, {**base, "challenge_ids": sorted(ticked)}, now)
            )
            new_state, more = _advance(state, course, now)
            return new_state, events + more

        case UntickStep():
            _require_step(state, action.step_index)
            _require_phase(state, Phase.CHALLENGES)
            if action.challenge_id not in state.step_ticked:
                raise InvalidTransition("Challenge is not ticked")
            step = course.steps[state.step_index]
            event = Event(
                EventType.CHALLENGE_UNTICKED,
                {**_step_payload(state, step), "scope": "step", "challenge_id": action.challenge_id},
                now,
            )
            return replace(state, step_ticked=state.step_ticked - {action.challenge_id}), [event]

        case TickGeneral():
            _require_general_open(state, now, general_deadline)
            if action.challenge_id not in unlocked_general(course, state):
                raise InvalidTransition("Challenge is not unlocked")
            if action.challenge_id in state.general_ticked:
                raise InvalidTransition("Challenge already ticked")
            event = Event(
                EventType.CHALLENGE_TICKED,
                {"scope": "general", "challenge_id": action.challenge_id, "text": action.text.strip()},
                now,
            )
            return replace(state, general_ticked=state.general_ticked | {action.challenge_id}), [event]

        case UntickGeneral():
            _require_general_open(state, now, general_deadline)
            if action.challenge_id not in state.general_ticked:
                raise InvalidTransition("Challenge is not ticked")
            event = Event(
                EventType.CHALLENGE_UNTICKED,
                {"scope": "general", "challenge_id": action.challenge_id},
                now,
            )
            return replace(state, general_ticked=state.general_ticked - {action.challenge_id}), [event]

    raise InvalidTransition(f"Unknown action {action!r}")


def _require_general_open(state: TeamState, now: datetime, general_deadline: datetime | None) -> None:
    _require_phase(state, *_STARTED)
    if general_deadline is not None and now >= general_deadline:
        raise InvalidTransition("General challenges are closed")
