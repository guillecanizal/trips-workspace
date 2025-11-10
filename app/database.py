"""Database helpers for the Trip Planner service."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

Base = declarative_base()


def init_engine(database_url: str) -> Engine:
    """Create the SQLAlchemy engine."""

    return create_engine(database_url, echo=False, future=True)


def create_session_factory(engine: Engine):
    """Return a scoped session factory bound to the engine."""

    return scoped_session(
        sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    )


def init_db(engine: Engine) -> None:
    """Create all tables if they do not exist."""

    from . import models  # noqa: F401  ensures models register with Base

    Base.metadata.create_all(bind=engine)
