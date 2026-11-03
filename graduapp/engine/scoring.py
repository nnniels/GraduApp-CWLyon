"""Score computed from the event log. Nothing is stored twice.

- General challenge: its points while ticked (a later untick removes them).
- Step: on STEP_SUCCEEDED, the step's bonus plus the points of its ticked challenges.
  On STEP_FAILED, nothing: a failed step still advances but brings no points home.
- Riddle answers are reviewed by the gamemaster. Give riddle steps points: 0 in the content.
- `duration` is the tie-breaker: GAME_ENDED minus GAME_STARTED.
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable

from .events import Event, EventType
from .states import Course


@dataclass(frozen=True)
class Score:
    total: int
    general: int
    steps: int
    steps_succeeded: int
    steps_failed: int
    duration: timedelta | None


def compute_score(events: Iterable[Event], course: Course) -> Score:
    steps_by_id = {s.id: s for s in course.steps}
    general_ticked: set[str] = set()
    steps_points = succeeded = failed = 0
    started = ended = None

    for e in events:
        payload = e.payload
        if e.type == EventType.GAME_STARTED:
            started = e.ts
        elif e.type == EventType.GAME_ENDED:
            ended = e.ts
        elif e.type == EventType.CHALLENGE_TICKED and payload["scope"] == "general":
            general_ticked.add(payload["challenge_id"])
        elif e.type == EventType.CHALLENGE_UNTICKED and payload["scope"] == "general":
            general_ticked.discard(payload["challenge_id"])
        elif e.type == EventType.STEP_SUCCEEDED:
            succeeded += 1
            steps_points += steps_by_id[payload["step_id"]].points
            steps_points += sum(course.points[c] for c in payload["challenge_ids"])
        elif e.type == EventType.STEP_FAILED:
            failed += 1

    general = sum(course.points[c] for c in general_ticked)
    duration = ended - started if started and ended else None
    return Score(general + steps_points, general, steps_points, succeeded, failed, duration)
