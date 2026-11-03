"""The only place that talks SQL during the game, and the bridge to the engine.

Public API
    load_course(conn, itinerary_id)         content rows -> engine Course
    apply_action(conn, team_id, action, now)  one transaction: load, transition, persist
    resolve_team(conn, team_id, now)        persist a pending expiry (call on page loads)
    get_view(conn, team_id)                 state + course, for rendering
    load_events / get_score                 audit log and computed score
    check_join_code / join_team / list_teams / get_team / rename_team
    get/set_general_deadline

Every write runs in a BEGIN IMMEDIATE transaction, so concurrent requests are serialised and a
double tap can never be applied twice.
"""
import hashlib
import hmac
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from ..engine.errors import InvalidTransition
from ..engine.events import Event, EventType
from ..engine.scoring import Score, compute_score
from ..engine.states import Course, Phase, StepDef, TeamState
from ..engine.transitions import Action, resolve_expiry, transition

GENERAL_DEADLINE_KEY = "general_deadline"
NAME_MAX_LENGTH = 40

# Not game transitions, so they live here and not in the engine. The score ignores them.
TEAM_JOINED = "TEAM_JOINED"
TEAM_RENAMED = "TEAM_RENAMED"
JOIN_REJECTED = "JOIN_REJECTED"


class UnknownTeam(LookupError):
    pass


@dataclass(frozen=True)
class TeamInfo:
    id: str
    name: str
    itinerary_id: str


@dataclass(frozen=True)
class Applied:
    state: TeamState
    events: list[Event]


@dataclass(frozen=True)
class TeamView:
    team: TeamInfo
    course: Course
    state: TeamState


# Time

def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("Datetimes must be timezone-aware")
    return dt.astimezone(timezone.utc).isoformat()


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@contextmanager
def _transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


# Settings

def get_general_deadline(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute(
        "SELECT value FROM game_setting WHERE key = ?", (GENERAL_DEADLINE_KEY,)
    ).fetchone()
    return _parse(row["value"]) if row else None


def set_general_deadline(conn: sqlite3.Connection, deadline: datetime | None) -> None:
    with conn:
        if deadline is None:
            conn.execute("DELETE FROM game_setting WHERE key = ?", (GENERAL_DEADLINE_KEY,))
        else:
            conn.execute(
                "INSERT INTO game_setting (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (GENERAL_DEADLINE_KEY, _iso(deadline)),
            )


# Teams

def _team_row(conn: sqlite3.Connection, team_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM team WHERE id = ?", (team_id,)).fetchone()
    if row is None:
        raise UnknownTeam(team_id)
    return row


def _info(row: sqlite3.Row) -> TeamInfo:
    return TeamInfo(row["id"], row["name"], row["itinerary_id"])


def list_teams(conn: sqlite3.Connection) -> list[TeamInfo]:
    return [_info(r) for r in conn.execute("SELECT * FROM team ORDER BY id")]


def get_team(conn: sqlite3.Connection, team_id: str) -> TeamInfo:
    return _info(_team_row(conn, team_id))


def _code_matches(expected: str, code: str) -> bool:
    """Constant-time comparison, ignoring case and surrounding spaces."""
    digest = lambda s: hashlib.sha256(s.strip().casefold().encode()).digest()
    return hmac.compare_digest(digest(expected), digest(code))


def check_join_code(conn: sqlite3.Connection, team_id: str, code: str) -> bool:
    return _code_matches(_team_row(conn, team_id)["join_code"], code)


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not 1 <= len(name) <= NAME_MAX_LENGTH:
        raise ValueError(f"The name must have 1 to {NAME_MAX_LENGTH} characters")
    return name


def _log(conn: sqlite3.Connection, team_id: str, type_: str, payload: dict, ts: datetime) -> None:
    conn.execute(
        "INSERT INTO event (team_id, type, payload_json, ts) VALUES (?, ?, ?, ?)",
        (team_id, type_, json.dumps(payload, sort_keys=True), _iso(ts)),
    )


def rename_team(conn: sqlite3.Connection, team_id: str, name: str) -> None:
    name = _clean_name(name)
    with conn:
        if conn.execute("UPDATE team SET name = ? WHERE id = ?", (name, team_id)).rowcount == 0:
            raise UnknownTeam(team_id)


def join_team(
    conn: sqlite3.Connection, team_id: str, code: str, name: str, now: datetime
) -> bool:
    """Screen A: check the code, then rename the team if asked, and log it. One transaction.

    Returns False on a wrong code (the attempt is logged, nothing else changes).
    The name is validated BEFORE the code, so a refusal for a bad name never reveals
    whether the code was right.
    """
    name = _clean_name(name)
    with _transaction(conn):
        team = _team_row(conn, team_id)
        if not _code_matches(team["join_code"], code):
            _log(conn, team_id, JOIN_REJECTED, {}, now)
            return False
        if name != team["name"]:
            conn.execute("UPDATE team SET name = ? WHERE id = ?", (name, team_id))
            _log(conn, team_id, TEAM_RENAMED, {"from": team["name"], "to": name}, now)
        _log(conn, team_id, TEAM_JOINED, {}, now)
    return True


# Content -> engine

def load_course(conn: sqlite3.Connection, itinerary_id: str) -> Course:
    steps = conn.execute(
        "SELECT s.* FROM itinerary_step i JOIN step s ON s.id = i.step_id "
        "WHERE i.itinerary_id = ? ORDER BY i.position",
        (itinerary_id,),
    ).fetchall()
    if not steps:
        raise LookupError(f"Itinerary '{itinerary_id}' has no steps")

    own: dict[str, list[str]] = {}
    points: dict[str, int] = {}
    at_start: set[str] = set()
    for c in conn.execute("SELECT * FROM challenge ORDER BY position"):
        points[c["id"]] = c["points"]
        if c["scope"] == "step":
            own.setdefault(c["step_id"], []).append(c["id"])
        elif c["unlocked_at_start"]:
            at_start.add(c["id"])

    unlocks: dict[str, list[str]] = {}
    for u in conn.execute("SELECT step_id, challenge_id FROM step_unlock ORDER BY challenge_id"):
        unlocks.setdefault(u["step_id"], []).append(u["challenge_id"])

    return Course(
        steps=tuple(
            StepDef(
                id=s["id"],
                code=s["code"],
                kind=s["kind"],
                points=s["points"],
                unlocks=tuple(unlocks.get(s["id"], ())),
                challenge_ids=tuple(own.get(s["id"], ())),
                k=s["challenge_k"] or 0,
                duration_s=s["challenge_duration_s"] or 0,
            )
            for s in steps
        ),
        general_at_start=frozenset(at_start),
        points=points,
    )


# State

def _load_state(conn: sqlite3.Connection, team_id: str, course: Course) -> TeamState:
    row = conn.execute("SELECT * FROM team_state WHERE team_id = ?", (team_id,)).fetchone()
    index = row["step_index"]
    current = course.steps[index].id if index < len(course.steps) else None

    step_ticked: set[str] = set()
    general_ticked: set[str] = set()
    for c in conn.execute(
        "SELECT c.id, c.scope, c.step_id FROM challenge_completion cc "
        "JOIN challenge c ON c.id = cc.challenge_id WHERE cc.team_id = ?",
        (team_id,),
    ):
        if c["scope"] == "general":
            general_ticked.add(c["id"])
        elif c["step_id"] == current:  # ticks of closed steps are history, not state
            step_ticked.add(c["id"])

    return TeamState(
        step_index=index,
        phase=Phase(row["phase"]),
        phase_deadline=_parse(row["phase_deadline"]),
        step_ticked=frozenset(step_ticked),
        general_ticked=frozenset(general_ticked),
    )


def _persist(conn: sqlite3.Connection, team_id: str, state: TeamState, events) -> None:
    conn.execute(
        "UPDATE team_state SET step_index = ?, phase = ?, phase_deadline = ? WHERE team_id = ?",
        (
            state.step_index,
            state.phase.value,
            _iso(state.phase_deadline) if state.phase_deadline else None,
            team_id,
        ),
    )
    for e in events:
        _log(conn, team_id, e.type, e.payload, e.ts)
        # Keep the challenge_completion projection in step with the log.
        if e.type == EventType.CHALLENGE_TICKED:
            conn.execute(
                "INSERT OR REPLACE INTO challenge_completion "
                "(team_id, challenge_id, text, ticked_at) VALUES (?, ?, ?, ?)",
                (team_id, e.payload["challenge_id"], e.payload["text"], _iso(e.ts)),
            )
        elif e.type == EventType.CHALLENGE_UNTICKED:
            conn.execute(
                "DELETE FROM challenge_completion WHERE team_id = ? AND challenge_id = ?",
                (team_id, e.payload["challenge_id"]),
            )


def get_view(conn: sqlite3.Connection, team_id: str) -> TeamView:
    team = _info(_team_row(conn, team_id))
    course = load_course(conn, team.itinerary_id)
    return TeamView(team, course, _load_state(conn, team_id, course))


def apply_action(
    conn: sqlite3.Connection, team_id: str, action: Action, now: datetime
) -> Applied:
    """Apply one action atomically.

    Raises InvalidTransition if the engine refuses it, after saving any expiry that the
    refused request revealed (a step that timed out has failed, whatever the request was).
    """
    refused: InvalidTransition | None = None
    with _transaction(conn):
        team = _team_row(conn, team_id)
        course = load_course(conn, team["itinerary_id"])
        state = _load_state(conn, team_id, course)
        try:
            new_state, events = transition(
                state, course, action, now, get_general_deadline(conn)
            )
        except InvalidTransition as exc:
            new_state, events, refused = exc.state, list(exc.events), exc
        _persist(conn, team_id, new_state, events)
    if refused:
        raise refused
    return Applied(new_state, events)


def resolve_team(conn: sqlite3.Connection, team_id: str, now: datetime) -> Applied:
    """Persist a pending expiry. Call before rendering a page."""
    with _transaction(conn):
        team = _team_row(conn, team_id)
        course = load_course(conn, team["itinerary_id"])
        state, events = resolve_expiry(_load_state(conn, team_id, course), course, now)
        if events:
            _persist(conn, team_id, state, events)
    return Applied(state, events)


# Log and score

def load_events(conn: sqlite3.Connection, team_id: str) -> list[Event]:
    return [
        Event(r["type"], json.loads(r["payload_json"]), _parse(r["ts"]))
        for r in conn.execute("SELECT * FROM event WHERE team_id = ? ORDER BY id", (team_id,))
    ]


def get_score(conn: sqlite3.Connection, team_id: str) -> Score:
    team = _team_row(conn, team_id)
    return compute_score(load_events(conn, team_id), load_course(conn, team["itinerary_id"]))
