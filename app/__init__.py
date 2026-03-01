"""Application factory for the Trip Planner service."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict

from flask import Flask

from .database import create_session_factory, init_db, init_engine


def create_app(test_config: Dict[str, Any] | None = None) -> Flask:
    """Create and configure the Flask application."""

    app = Flask(__name__)
    instance_path = Path(app.instance_path)
    instance_path.mkdir(parents=True, exist_ok=True)

    default_db_path = instance_path / "trip_planner.db"
    app.config.from_mapping(
        DATABASE_URL=f"sqlite:///{default_db_path}",
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-key"),
    )

    if test_config:
        app.config.update(test_config)

    engine = init_engine(app.config["DATABASE_URL"])
    session_factory = create_session_factory(engine)
    init_db(engine)

    app.session_factory = session_factory  # type: ignore[attr-defined]

    from .routes import bp as main_bp

    app.register_blueprint(main_bp)

    # Make timedelta available in all Jinja2 templates
    app.jinja_env.globals["timedelta"] = timedelta

    return app
