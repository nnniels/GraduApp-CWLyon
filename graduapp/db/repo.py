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


@dataclass(frozen=True)
class ChallengeInfo:
    id: str
    text: str


@dataclass(frozen=True)
class StepContent:
    """What a screen may show about a step. Deliberately has no `code` field."""

    id: str
    kind: str
    location: dict
    riddle_text: str | None
    riddle_image: str | None
    k: int
    duration_s: int
    challenges: tuple[ChallengeInfo, ...]
    fun_fact: str | None = None


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

def get_step_content(conn: sqlite3.Connection, step_id: str) -> StepContent:
    s = conn.execute(
        "SELECT id, kind, location_json, riddle_text, riddle_image, challenge_k, "
        "challenge_duration_s, fun_fact FROM step WHERE id = ?",
        (step_id,),
    ).fetchone()
    if s is None:
        raise LookupError(step_id)
    challenges = tuple(
        ChallengeInfo(c["id"], c["text"])
        for c in conn.execute(
            "SELECT id, text FROM challenge WHERE step_id = ? ORDER BY position", (step_id,)
        )
    )
    return StepContent(
        s["id"], s["kind"], json.loads(s["location_json"]), s["riddle_text"], s["riddle_image"],
        s["challenge_k"] or 0, s["challenge_duration_s"] or 0, challenges,
                s["fun_fact"],
    )


def challenge_texts(conn: sqlite3.Connection, ids: list[str]) -> dict[str, str]:
    rows = conn.execute(
        "SELECT id, text FROM challenge WHERE id IN (SELECT value FROM json_each(?))",
        (json.dumps(list(ids)),),
    )
    return {r["id"]: r["text"] for r in rows}


def list_general_challenges(
    conn: sqlite3.Connection, ids: frozenset[str] | set[str]
) -> list[ChallengeInfo]:
    """The given general challenges, in the order the author wrote them."""
    rows = conn.execute(
        "SELECT id, text FROM challenge WHERE scope = 'general' "
        "AND id IN (SELECT value FROM json_each(?)) ORDER BY position",
        (json.dumps(sorted(ids)),),
    )
    return [ChallengeInfo(r["id"], r["text"]) for r in rows]


def get_seen_general(conn: sqlite3.Connection, team_id: str) -> frozenset[str]:
    rows = conn.execute("SELECT challenge_id FROM challenge_seen WHERE team_id = ?", (team_id,))
    return frozenset(r["challenge_id"] for r in rows)


def mark_general_seen(conn: sqlite3.Connection, team_id: str, ids) -> None:
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO challenge_seen (team_id, challenge_id) VALUES (?, ?)",
            [(team_id, i) for i in ids],
        )


def get_completion_texts(conn: sqlite3.Connection, team_id: str) -> dict[str, str]:
    """What the team typed when ticking, by challenge id (current ticks only)."""
    rows = conn.execute(
        "SELECT challenge_id, text FROM challenge_completion WHERE team_id = ?", (team_id,)
    )
    return {r["challenge_id"]: r["text"] for r in rows}

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


def reset_game(conn: sqlite3.Connection, names: dict[str, str] | None = None) -> int:
    """Back to the pre-game state: every team NOT_STARTED, no ticks, empty event log.

    Kept: content, teams, join codes, and game settings (general_deadline).
    `names` ({team_id: name}) also restores team names. Returns the number of events deleted.
    One transaction, so a running app never sees a half-reset game.
    """
    with _transaction(conn):
        deleted = conn.execute("SELECT COUNT(*) FROM event").fetchone()[0]
        conn.execute("DELETE FROM challenge_completion")
        conn.execute("DELETE FROM challenge_seen")
        conn.execute("DELETE FROM event")
        conn.execute(
            "UPDATE team_state SET step_index = 0, phase = 'NOT_STARTED', phase_deadline = NULL"
        )
        for team_id, name in (names or {}).items():
            conn.execute("UPDATE team SET name = ? WHERE id = ?", (_clean_name(name), team_id))
    return deleted


# Log and score

@dataclass(frozen=True)
class LoggedEvent:
    id: int
    team_id: str
    type: str
    payload: dict
    ts: datetime


def list_events(conn: sqlite3.Connection, team_id: str | None = None) -> list[LoggedEvent]:
    """The raw audit log, oldest first. Used by `flask show-events` and the organiser view."""
    sql, args = "SELECT * FROM event", ()
    if team_id is not None:
        sql, args = sql + " WHERE team_id = ?", (team_id,)
    return [
        LoggedEvent(r["id"], r["team_id"], r["type"], json.loads(r["payload_json"]), _parse(r["ts"]))
        for r in conn.execute(sql + " ORDER BY id", args)
    ]

def list_events_page(
    conn: sqlite3.Connection,
    team_id: str | None = None,
    before_id: int | None = None,
    limit: int = 200,
) -> list[LoggedEvent]:
    """Newest first. Pass the id of the last row as `before_id` to get the next page."""
    where, args = [], []
    if team_id is not None:
        where.append("team_id = ?")
        args.append(team_id)
    if before_id is not None:
        where.append("id < ?")
        args.append(before_id)
    sql = "SELECT * FROM event"
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))
    return [
        LoggedEvent(r["id"], r["team_id"], r["type"], json.loads(r["payload_json"]), _parse(r["ts"]))
        for r in rows
    ]


def load_events(conn: sqlite3.Connection, team_id: str) -> list[Event]:
    return [
        Event(r["type"], json.loads(r["payload_json"]), _parse(r["ts"]))
        for r in conn.execute("SELECT * FROM event WHERE team_id = ? ORDER BY id", (team_id,))
    ]


def get_score(conn: sqlite3.Connection, team_id: str) -> Score:
    team = _team_row(conn, team_id)
    return compute_score(load_events(conn, team_id), load_course(conn, team["itinerary_id"]))


# Organiser view. Read-only, and it deliberately exposes validation and join codes:
# only web/admin.py may call the functions below.

@dataclass(frozen=True)
class TeamOverview:
    id: str
    name: str
    itinerary_id: str
    phase: Phase
    step_index: int
    n_steps: int
    step_label: str | None
    code: str | None  # the code the team has to enter next
    deadline: datetime | None
    score: Score
    ticked: int
    k: int
    wrong_codes: int
    last_activity: datetime | None


@dataclass
class AnswerRow:
    ts: datetime
    scope: str  # "riddle", "step" or "general"
    challenge_id: str | None
    prompt: str
    text: str
    lost: bool = False  # ticked in a step that failed: brings no points


@dataclass
class StepReport:
    step_id: str
    label: str
    outcome: str | None  # "succeeded", "failed", or None while not closed
    rows: list[AnswerRow]


@dataclass(frozen=True)
class TeamReport:
    team: TeamInfo
    steps: list[StepReport]
    general: list[AnswerRow]


@dataclass(frozen=True)
class CodeRow:
    position: int
    step_id: str
    label: str
    kind: str
    code: str


def step_labels(conn: sqlite3.Connection) -> dict[str, str]:
    """Location label, else location text, else the step id: steps have no title."""
    labels = {}
    for r in conn.execute("SELECT id, location_json FROM step"):
        loc = json.loads(r["location_json"])
        labels[r["id"]] = loc.get("label") or loc.get("text") or r["id"]
    return labels


def all_challenge_texts(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["id"]: r["text"] for r in conn.execute("SELECT id, text FROM challenge")}


def list_overview(conn: sqlite3.Connection) -> list[TeamOverview]:
    labels = step_labels(conn)
    wrong = {
        r["team_id"]: r["n"]
        for r in conn.execute(
            "SELECT team_id, COUNT(*) AS n FROM event WHERE type = ? GROUP BY team_id",
            (EventType.CODE_REJECTED,),
        )
    }
    last = {
        r["team_id"]: _parse(r["last"])
        for r in conn.execute("SELECT team_id, MAX(ts) AS last FROM event GROUP BY team_id")
    }
    rows = []
    for team in list_teams(conn):
        course = load_course(conn, team.itinerary_id)
        state = _load_state(conn, team.id, course)
        current = course.steps[state.step_index] if state.step_index < len(course.steps) else None
        waiting = state.phase in (Phase.NOT_STARTED, Phase.GOING)
        in_challenges = state.phase == Phase.CHALLENGES
        rows.append(
            TeamOverview(
                id=team.id,
                name=team.name,
                itinerary_id=team.itinerary_id,
                phase=state.phase,
                step_index=state.step_index,
                n_steps=len(course.steps),
                step_label=labels[current.id] if current else None,
                code=current.code if current and waiting else None,
                deadline=state.phase_deadline,
                score=get_score(conn, team.id),
                ticked=len(state.step_ticked) if in_challenges else 0,
                k=current.k if current and in_challenges else 0,
                wrong_codes=wrong.get(team.id, 0),
                last_activity=last.get(team.id),
            )
        )
    return rows


def get_team_report(conn: sqlite3.Connection, team_id: str) -> TeamReport:
    """What the team typed, by step, rebuilt from the event log (unticked notes are dropped)."""
    team = _info(_team_row(conn, team_id))
    course = load_course(conn, team.itinerary_id)
    labels = step_labels(conn)
    challenges = all_challenge_texts(conn)
    riddles = {r["id"]: r["riddle_text"] for r in conn.execute("SELECT id, riddle_text FROM step")}
    steps = {s.id: StepReport(s.id, labels[s.id], None, []) for s in course.steps}
    general: list[AnswerRow] = []

    for e in load_events(conn, team_id):
        p = e.payload
        if e.type == EventType.RIDDLE_ANSWERED:
            steps[p["step_id"]].rows.append(
                AnswerRow(e.ts, "riddle", None, riddles.get(p["step_id"]) or "", p["text"])
            )
        elif e.type == EventType.CHALLENGE_TICKED:
            row = AnswerRow(
                e.ts, p["scope"], p["challenge_id"], challenges.get(p["challenge_id"], ""), p["text"]
            )
            (general if p["scope"] == "general" else steps[p["step_id"]].rows).append(row)
        elif e.type == EventType.CHALLENGE_UNTICKED:
            target = general if p["scope"] == "general" else steps[p["step_id"]].rows
            target[:] = [r for r in target if r.challenge_id != p["challenge_id"]]
        elif e.type == EventType.STEP_SUCCEEDED:
            steps[p["step_id"]].outcome = "succeeded"
        elif e.type == EventType.STEP_FAILED:
            step = steps[p["step_id"]]
            step.outcome = "failed"
            for r in step.rows:
                r.lost = r.scope == "step"
    return TeamReport(team, list(steps.values()), general)


def list_itinerary_codes(conn: sqlite3.Connection) -> list[tuple[str, str, list[CodeRow]]]:
    """(itinerary id, title, ordered steps with their validation codes)."""
    labels = step_labels(conn)
    out = []
    for it in conn.execute("SELECT id, title FROM itinerary ORDER BY id"):
        rows = [
            CodeRow(r["position"], r["id"], labels[r["id"]], r["kind"], r["code"])
            for r in conn.execute(
                "SELECT i.position, s.id, s.kind, s.code FROM itinerary_step i "
                "JOIN step s ON s.id = i.step_id WHERE i.itinerary_id = ? ORDER BY i.position",
                (it["id"],),
            )
        ]
        out.append((it["id"], it["title"], rows))
    return out


def list_join_codes(conn: sqlite3.Connection) -> list[tuple[TeamInfo, str]]:
    return [
        (_info(r), r["join_code"])
        for r in conn.execute("SELECT * FROM team ORDER BY id")
    ]
