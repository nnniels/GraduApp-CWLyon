from flask import Flask

from .config import Config


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

    from .cli import seed_command
    from .web.player import bp as player_bp
    from .web.admin import bp as admin_bp

    app.cli.add_command(seed_command)
    app.register_blueprint(player_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    return app
