from dataclasses import dataclass
from datetime import datetime


class EventType:
    GAME_STARTED = "GAME_STARTED"
    CODE_REJECTED = "CODE_REJECTED"
    ARRIVED = "ARRIVED"
    CHALLENGES_UNLOCKED = "CHALLENGES_UNLOCKED"
    CHALLENGE_PHASE_STARTED = "CHALLENGE_PHASE_STARTED"
    RIDDLE_ANSWERED = "RIDDLE_ANSWERED"
    CHALLENGE_TICKED = "CHALLENGE_TICKED"
    CHALLENGE_UNTICKED = "CHALLENGE_UNTICKED"
    STEP_SUCCEEDED = "STEP_SUCCEEDED"
    STEP_FAILED = "STEP_FAILED"
    GAME_ENDED = "GAME_ENDED"


@dataclass(frozen=True)
class Event:
    """An entry of the audit log. The payload must stay JSON-serialisable."""

    type: str
    payload: dict
    ts: datetime
