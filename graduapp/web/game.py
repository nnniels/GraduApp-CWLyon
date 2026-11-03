"""Screen B: the team's game. HTMX partials over the engine.

Every route answers with the SAME response (partials/response.html): the panel, plus an
out-of-band swap of the popup container. This keeps one rule for the whole screen: any request
may reveal a timed-out step, and the phone is always shown the true state.
"""
import math
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import quote

from flask import (
    Blueprint,
    current_app,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from ..db import repo
from ..engine.errors import InvalidTransition
from ..engine.events import EventType as E
from ..engine.states import Phase
from ..engine.transitions import Arrive, Start, SubmitRiddle, TickStep, UntickStep
from .auth import current_team
from .db import get_db

bp = Blueprint("game", __name__, url_prefix="/game")

POPUP_CODE = "partials/popup_code.html"
POPUP_CHALLENGE = "partials/popup_challenge.html"
POPUP_NOTICE = "partials/popup_notice.html"

RIDDLE_MAX_LENGTH = 1000
PROOF_MAX_LENGTH = 500


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _int(name: str) -> int:
    try:
        return int(request.form.get(name, ""))
    except ValueError:
        return -1  # never matches a step: handled as a stale screen


def team_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        team = current_team(get_db())
        if team is None:
            if request.headers.get("HX-Request"):
                return "", 200, {"HX-Redirect": url_for("player.index")}
            return redirect(url_for("player.index"))
        g.team = team
        return view(*args, **kwargs)

    return wrapped


# View model

def _location(raw: dict) -> dict:
    kind = raw["kind"]
    if kind == "minimap":
        lat, lon = raw["lat"], raw["lon"]
        bbox = ",".join(f"{v:.5f}" for v in (lon - 0.004, lat - 0.0025, lon + 0.004, lat + 0.0025))
        return {
            "kind": kind,
            "label": raw.get("label"),
            "embed": "https://www.openstreetmap.org/export/embed.html"
            f"?bbox={quote(bbox, safe='')}&layer=mapnik&marker={quote(f'{lat},{lon}', safe='')}",
            "link": f"https://www.google.com/maps?q={lat},{lon}",
        }
    return dict(raw)


def _notice(conn, events) -> dict | None:
    """The popup text explaining what just happened, built from the events."""
    lines: list[tuple[str, str]] = []
    unlocked_ids: list[str] = []
    for e in events:
        if e.type == E.ARRIVED:
            lines.append(("ok", "Location reached!"))
        elif e.type == E.CHALLENGES_UNLOCKED:
            unlocked_ids += e.payload["challenge_ids"]
        elif e.type == E.STEP_SUCCEEDED and e.payload["challenge_ids"]:
            lines.append(("ok", "Location validated!"))
        elif e.type == E.STEP_FAILED:
            lines.append(("fail", "Time is up: the challenges are failed."))
    if not lines and not unlocked_ids:
        return None
    texts = repo.challenge_texts(conn, unlocked_ids)
    return {"lines": lines, "unlocked": [texts[i] for i in unlocked_ids if i in texts]}


def _context(conn, team_id, events=(), popup=None, popup_ctx=None) -> dict:
    now = _now()
    view = repo.get_view(conn, team_id)
    state, course = view.state, view.course
    ctx = {
        "team": view.team,
        "phase": state.phase.value,
        "step_index": state.step_index,
        "step_number": min(state.step_index + 1, len(course.steps)),
        "total_steps": len(course.steps),
    }
    if state.phase in (Phase.GOING, Phase.RIDDLE, Phase.CHALLENGES):
        step = repo.get_step_content(conn, course.steps[state.step_index].id)
        ctx["step"] = step
        ctx["location"] = _location(step.location)
    if state.phase is Phase.CHALLENGES:
        remaining = max(0, math.ceil((state.phase_deadline - now).total_seconds()))
        ctx.update(
            challenges=[
                {"id": c.id, "text": c.text, "ticked": c.id in state.step_ticked}
                for c in step.challenges
            ],
            k=step.k,
            ticked_count=len(state.step_ticked),
            remaining_label=f"{remaining // 60:02d}:{remaining % 60:02d}",
            deadline=state.phase_deadline.isoformat(),
            server_now=now.isoformat(),
        )

    if any(e.type == E.CODE_REJECTED for e in events):
        popup, popup_ctx = POPUP_CODE, {"error": "Wrong code"}
    if popup is None:
        notice = _notice(conn, events)
        if notice:
            popup, popup_ctx = POPUP_NOTICE, {"notice": notice}
    ctx["popup"] = popup
    ctx.update(popup_ctx or {})
    return ctx


def _respond(events=(), popup=None, popup_ctx=None):
    ctx = _context(get_db(), g.team.id, events, popup, popup_ctx)
    return render_template("partials/response.html", **ctx)


def render_game_page(conn, team):
    """Full page for GET /. Also records any expiry that happened while the phone was away."""
    events = repo.resolve_team(conn, team.id, _now()).events
    return render_template("pages/game.html", **_context(conn, team.id, events))


def _do(action):
    try:
        events = repo.apply_action(get_db(), g.team.id, action, _now()).events
    except InvalidTransition as exc:
        # Stale or impossible action: show the true state. Keep any expiry it revealed.
        events = list(exc.events)
    return _respond(events)


# Routes

@bp.get("/panel")
@team_required
def panel():
    return _respond(repo.resolve_team(get_db(), g.team.id, _now()).events)


@bp.post("/start")
@team_required
def start():
    return _do(Start())


@bp.get("/arrive")
@team_required
def arrive_form():
    events = repo.resolve_team(get_db(), g.team.id, _now()).events
    state = repo.get_view(get_db(), g.team.id).state
    if state.phase is not Phase.GOING:
        return _respond(events)
    return _respond(events, POPUP_CODE, {"error": None})


@bp.post("/arrive")
@team_required
def arrive():
    return _do(Arrive(_int("step_index"), request.form.get("code", "")))


@bp.post("/riddle")
@team_required
def riddle():
    text = request.form.get("text", "")[:RIDDLE_MAX_LENGTH]
    return _do(SubmitRiddle(_int("step_index"), text))


@bp.get("/challenge/<challenge_id>")
@team_required
def challenge_popup(challenge_id: str):
    conn = get_db()
    events = repo.resolve_team(conn, g.team.id, _now()).events
    view = repo.get_view(conn, g.team.id)
    state = view.state
    if state.phase is not Phase.CHALLENGES:
        return _respond(events)
    step = repo.get_step_content(conn, view.course.steps[state.step_index].id)
    info = next((c for c in step.challenges if c.id == challenge_id), None)
    if info is None:
        return _respond(events)
    ticked = challenge_id in state.step_ticked
    proof = repo.get_completion_texts(conn, g.team.id).get(challenge_id, "") if ticked else ""
    return _respond(
        events, POPUP_CHALLENGE, {"challenge": info, "challenge_ticked": ticked, "proof": proof}
    )


@bp.post("/tick")
@team_required
def tick():
    text = request.form.get("text", "")[:PROOF_MAX_LENGTH]
    return _do(TickStep(_int("step_index"), request.form.get("challenge_id", ""), text))


@bp.post("/untick")
@team_required
def untick():
    return _do(UntickStep(_int("step_index"), request.form.get("challenge_id", "")))


@bp.get("/media/<path:filename>")
@team_required
def media(filename: str):
    """Riddle images, from CONTENT_DIR/images. Only for logged-in phones."""
    folder = Path(current_app.config["CONTENT_DIR"]).resolve() / "images"
    return send_from_directory(folder, filename)
