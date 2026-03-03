"""Shared pytest fixtures for the Trip Planner test suite."""

from __future__ import annotations

import pytest

from app import create_app
from app.models import Activity, Day, GeneralItem, Trip


@pytest.fixture
def app():
    """Flask app configured with an in-memory SQLite database."""
    flask_app = create_app(
        {
            "DATABASE_URL": "sqlite:///:memory:",
            "TESTING": True,
            "SECRET_KEY": "test-secret",
        }
    )
    with flask_app.app_context():
        yield flask_app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def db_session(app):
    """Raw SQLAlchemy session for setting up test data."""
    session = app.session_factory()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def make_trip(
    db_session,
    *,
    name: str = "Test Trip",
    start: str = "2026-06-01",
    end: str = "2026-06-03",
) -> Trip:
    """Create and commit a minimal Trip with sequential days."""
    from datetime import date, timedelta

    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    trip = Trip(name=name, start_date=start_date, end_date=end_date)
    db_session.add(trip)
    db_session.flush()

    current = start_date
    while current <= end_date:
        db_session.add(Day(trip=trip, date=current))
        current += timedelta(days=1)

    db_session.commit()
    db_session.refresh(trip)
    return trip
