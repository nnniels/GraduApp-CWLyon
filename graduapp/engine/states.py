"""Engine data structures: what a team's state is, and what the game looks like to the engine.

The engine has its own small definitions (StepDef, Course) instead of importing the content
package: the db layer maps content into them. Datetimes must all be timezone-aware (UTC).
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping


class Phase(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    GOING = "GOING"
    RIDDLE = "RIDDLE"
    CHALLENGES = "CHALLENGES"
    ENDED = "ENDED"


@dataclass(frozen=True)
class TeamState:
    step_index: int = 0
    phase: Phase = Phase.NOT_STARTED
    phase_deadline: datetime | None = None
    # Ticked challenges of the current step only. Cleared when the step closes.
    step_ticked: frozenset[str] = frozenset()
    general_ticked: frozenset[str] = frozenset()


@dataclass(frozen=True)
class StepDef:
    id: str
    code: str
    kind: str  # "riddle" or "challenges"
    points: int = 0
    unlocks: tuple[str, ...] = ()
    challenge_ids: tuple[str, ...] = ()
    k: int = 0
    duration_s: int = 0


@dataclass(frozen=True)
class Course:
    """What one team plays: its ordered steps, plus the general challenges."""

    steps: tuple[StepDef, ...]
    general_at_start: frozenset[str] = frozenset()
    # Points of every challenge, step and general, by id.
    points: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if not self.steps:
            raise ValueError("A course needs at least one step")


def unlocked_general(course: Course, state: TeamState) -> frozenset[str]:
    """General challenges visible on screen C. Derived, never stored.

    A step counts as reached once the team has arrived at it (phase RIDDLE or CHALLENGES),
    or has moved past it.
    """
    reached = state.step_index + (1 if state.phase in (Phase.RIDDLE, Phase.CHALLENGES) else 0)
    unlocked = set(course.general_at_start)
    for step in course.steps[:reached]:
        unlocked.update(step.unlocks)
    return frozenset(unlocked)
