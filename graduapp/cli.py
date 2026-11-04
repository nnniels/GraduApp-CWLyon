import json

import click
from flask import current_app
from flask.cli import with_appcontext

from .content.loader import load_content
from .content.schema import ContentError
from .db import repo
from .db.connection import connect, init_db
from .db.seed import SeedError, seed


@click.command("show-events")
@click.option("--team", help="Only the events of this team id.")
@click.option("--tail", type=int, default=0, help="Only the last N events.")
@with_appcontext
def show_events_command(team: str | None, tail: int) -> None:
    """Print the audit log (read-only). Times are UTC."""
    events = repo.list_events(connect(current_app.config["DATABASE_PATH"]), team)
    if tail > 0:
        events = events[-tail:]
    if not events:
        click.echo("No events.")
        return
    click.echo(f"{'id':>4}  {'time (UTC)':<19}  {'team':<10}  {'type':<24}  payload")
    for e in events:
        payload = json.dumps(e.payload, ensure_ascii=False)
        click.echo(f"{e.id:>4}  {e.ts:%Y-%m-%d %H:%M:%S}  {e.team_id:<10}  {e.type:<24}  {payload}")


@click.command("reset-game")
@click.option("--names", "restore_names", is_flag=True,
              help="Also restore the team names from content/teams.yaml.")
@click.option("--yes", is_flag=True, help="Do not ask for confirmation.")
@with_appcontext
def reset_game_command(restore_names: bool, yes: bool) -> None:
    """Reset all teams to NOT_STARTED and erase the event log and ticks.

    Keeps content, teams, join codes and the general-challenges deadline.
    Stop other writers first if you can; the reset itself is one transaction.
    """
    try:
        names = None
        if restore_names:
            names = {t.id: t.name for t in load_content(current_app.config["CONTENT_DIR"]).teams}
        conn = connect(current_app.config["DATABASE_PATH"])
        init_db(conn)
        if not yes:
            click.confirm(
                "This erases ALL progress, ticks and history for every team. Continue?", abort=True
            )
        deleted = repo.reset_game(conn, names)
    except ContentError as exc:
        raise click.ClickException(str(exc))
    suffix = " Team names restored." if restore_names else ""
    click.echo(f"Game reset: {deleted} events deleted, all teams back to NOT_STARTED.{suffix}")


@click.command("seed")
@click.option("--force", is_flag=True, help="Re-seed even if some team has started.")
@with_appcontext
def seed_command(force: bool) -> None:
    """Validate content/*.yaml and load it into the database."""
    try:
        content = load_content(current_app.config["CONTENT_DIR"])
        conn = connect(current_app.config["DATABASE_PATH"])
        init_db(conn)
        seed(conn, content, force=force)
    except (ContentError, SeedError) as exc:
        raise click.ClickException(str(exc))
    click.echo(
        f"Seeded {len(content.steps)} steps, {len(content.itineraries)} itineraries, "
        f"{len(content.teams)} teams."
    )
