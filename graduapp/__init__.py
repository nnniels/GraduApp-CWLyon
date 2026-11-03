import logging

from flask import Flask

from .config import Config

log = logging.getLogger(__name__)


def create_app(config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder="web/templates",
        static_folder="web/static",
    )
    app.config.from_object(Config)
    if config:
        app.config.update(config)

    if app.config["SECRET_KEY"] in ("", "change-me"):  # unset, or the .env.example placeholder
        if not (app.debug or app.testing):
            raise RuntimeError("SECRET_KEY is not set. Put a random one in .env (see .env.example).")
        log.warning("SECRET_KEY not set: using an insecure development key")
        app.config["SECRET_KEY"] = "insecure-development-key"

    from .cli import seed_command, show_events_command
    from .web import db
    from .web.auth import limiter
    from .web.game import bp as game_bp
    from .web.player import bp as player_bp
    from .web.admin import bp as admin_bp

    db.init_app(app)
    limiter.init_app(app)
    app.cli.add_command(seed_command)
    app.cli.add_command(show_events_command)
    app.register_blueprint(player_bp)
    app.register_blueprint(game_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    return app
