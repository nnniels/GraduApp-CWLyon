"""Organiser view: a read-only utility, behind one shared password.

Everything here is fail-closed (no password configured = 404) and uncached, because the pages
show validation codes and what the players typed. Plain full pages, no HTMX: reload to refresh.
"""
import csv
import io
import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
)

from ..db import repo
from ..engine.events import EventType as E
from . import auth
from .auth import limiter
from .db import get_db

log = logging.getLogger(__name__)
bp = Blueprint("admin", __name__)

PAGE_SIZE = 200
DEADLINE_FORMATS = ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S")
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tz() -> ZoneInfo:
    return ZoneInfo(current_app.config["DISPLAY_TZ"])


@bp.app_template_filter("local")
def local(dt: datetime | None, fmt: str = TIME_FORMAT) -> str:
    return dt.astimezone(_tz()).strftime(fmt) if dt else "-"


@bp.before_request
def guard():
    if not auth.admin_enabled():
        abort(404)
    if request.endpoint != "admin.login" and not auth.admin_logged_in():
        return redirect(url_for("admin.login"), code=303)


@bp.after_request
def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


# Login

@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(
    lambda: current_app.config["ADMIN_LOGIN_RATE_LIMIT"],
    methods=["POST"],
    key_func=auth.client_ip,
    deduct_when=lambda response: response.status_code == 401,  # wrong passwords only
)
def login():
    if request.method == "POST":
        if auth.check_admin_password(request.form.get("password", "")):
            auth.admin_login()
            return redirect(url_for("admin.teams"), code=303)
        return render_template("admin/login.html", error="Wrong password"), 401
    return render_template("admin/login.html", error=None)


@bp.post("/logout")
def logout():
    auth.admin_logout()
    return redirect(url_for("player.index"), code=303)


@bp.get("/")
def index():
    return redirect(url_for("admin.teams"), code=303)


# Tab 1: teams

def _teams_page(error: str | None = None, status: int = 200):
    conn = get_db()
    now = _now()
    for t in repo.list_teams(conn):
        repo.resolve_team(conn, t.id, now)  # an idle phone must not show a stale step
    page = render_template(
        "admin/teams.html",
        rows=repo.list_overview(conn),
        deadline=repo.get_general_deadline(conn),
        now=now,
        error=error,
    )
    return page, status


@bp.get("/teams")
def teams():
    return _teams_page()


@bp.get("/teams/<team_id>")
def team(team_id: str):
    conn = get_db()
    try:
        repo.resolve_team(conn, team_id, _now())
        report = repo.get_team_report(conn, team_id)
    except repo.UnknownTeam:
        abort(404)
    return render_template("admin/team.html", report=report, score=repo.get_score(conn, team_id))


@bp.post("/deadline")
def set_deadline():
    conn = get_db()
    if request.form.get("action") == "clear":
        repo.set_general_deadline(conn, None)
        log.info("general deadline cleared")
        return redirect(url_for("admin.teams"), code=303)

    raw = request.form.get("deadline", "").strip()
    for fmt in DEADLINE_FORMATS:
        try:
            deadline = datetime.strptime(raw, fmt).replace(tzinfo=_tz())
            break
        except ValueError:
            continue
    else:
        return _teams_page("Invalid date", 400)
    repo.set_general_deadline(conn, deadline)
    log.info("general deadline set to %s", deadline.isoformat())
    return redirect(url_for("admin.teams"), code=303)


# Tab 2: log

def _describe(event: repo.LoggedEvent, labels: dict, challenges: dict) -> str:
    p = event.payload
    step = labels.get(p.get("step_id", ""), p.get("step_id", "?"))
    challenge = challenges.get(p.get("challenge_id", ""), p.get("challenge_id", "?"))
    match event.type:
        case repo.TEAM_JOINED:
            return "joined"
        case repo.TEAM_RENAMED:
            return f'renamed "{p["from"]}" to "{p["to"]}"'
        case repo.JOIN_REJECTED:
            return "wrong join code"
        case E.GAME_STARTED:
            return "started the game"
        case E.CODE_REJECTED:
            return f'wrong code "{p["code"]}" at {step}'
        case E.ARRIVED:
            return f"arrived at {step}"
        case E.CHALLENGES_UNLOCKED:
            return f'unlocked {len(p["challenge_ids"])} general challenge(s)'
        case E.CHALLENGE_PHASE_STARTED:
            return f'challenges started at {step} (need {p["k"]})'
        case E.RIDDLE_ANSWERED:
            return f'answered at {step}: "{p["text"]}"'
        case E.CHALLENGE_TICKED:
            return f'ticked "{challenge}" ({p["scope"]}): "{p["text"]}"'
        case E.CHALLENGE_UNTICKED:
            return f'unticked "{challenge}" ({p["scope"]})'
        case E.STEP_SUCCEEDED:
            return f"succeeded {step}"
        case E.STEP_FAILED:
            return f"failed {step} (no points)"
        case E.GAME_ENDED:
            return "finished the game"
        case _:
            return event.type


def _int_arg(name: str) -> int | None:
    try:
        return int(request.args[name])
    except (KeyError, ValueError):
        return None


@bp.get("/log")
def log_page():
    conn = get_db()
    team_id = request.args.get("team") or None
    events = repo.list_events_page(conn, team_id, _int_arg("before"), PAGE_SIZE)
    labels, challenges = repo.step_labels(conn), repo.all_challenge_texts(conn)
    all_teams = repo.list_teams(conn)
    return render_template(
        "admin/log.html",
        rows=[(e, _describe(e, labels, challenges), json.dumps(e.payload, ensure_ascii=False)) for e in events],
        teams=all_teams,
        names={t.id: t.name for t in all_teams},
        team_id=team_id,
        older=events[-1].id if len(events) == PAGE_SIZE else None,
    )


# Tab 3: codes

@bp.get("/codes")
def codes():
    conn = get_db()
    return render_template(
        "admin/codes.html",
        itineraries=repo.list_itinerary_codes(conn),
        join_codes=repo.list_join_codes(conn),
    )


# CSV

def _cell(value):
    """Players type free text: a cell starting with = + - @ would run as a formula in Excel."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _csv(filename: str, header: list[str], rows) -> Response:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(c) for c in row])
    return Response(
        "\ufeff" + out.getvalue(),  # the BOM makes Excel read UTF-8 (accents in player text)
        content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.get("/events.csv")
def events_csv():
    conn = get_db()
    team_id = request.args.get("team") or None
    names = {t.id: t.name for t in repo.list_teams(conn)}
    labels, challenges = repo.step_labels(conn), repo.all_challenge_texts(conn)
    events = reversed(repo.list_events_page(conn, team_id, None, limit=-1))
    return _csv(
        "events.csv",
        ["id", "time", "team_id", "team", "type", "description", "payload"],
        (
            [
                e.id, local(e.ts), e.team_id, names.get(e.team_id, ""), e.type,
                _describe(e, labels, challenges), json.dumps(e.payload, ensure_ascii=False),
            ]
            for e in events
        ),
    )


@bp.get("/answers.csv")
def answers_csv():
    conn = get_db()

    def rows():
        for t in repo.list_teams(conn):
            report = repo.get_team_report(conn, t.id)
            sections = [(s.label, s.rows) for s in report.steps] + [("(general)", report.general)]
            for label, answers in sections:
                for a in answers:
                    yield [
                        t.id, t.name, label, a.scope, a.prompt, a.text,
                        "no points (failed step)" if a.lost else "", local(a.ts),
                    ]

    return _csv(
        "answers.csv",
        ["team_id", "team", "step", "kind", "prompt", "answer", "note", "time"],
        rows(),
    )

