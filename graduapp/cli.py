import click
from flask import current_app
from flask.cli import with_appcontext

from .content.loader import load_content
from .content.schema import ContentError
from .db.connection import connect, init_db
from .db.seed import SeedError, seed


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
