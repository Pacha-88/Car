"""Engine/session setup.

Defaults to a local SQLite file so the whole pipeline runs with zero
external setup during development. Point DATABASE_URL at Supabase/Postgres
(e.g. "postgresql+psycopg://...") to switch targets without touching the
models — that swap is deferred to the phase where we actually deploy.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from car_tracker.db.models import Base

DEFAULT_SQLITE_PATH = "car_tracker.db"


def get_engine(database_url: str | None = None):
    url = database_url or os.environ.get("DATABASE_URL") or f"sqlite:///{DEFAULT_SQLITE_PATH}"
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def init_db(engine=None) -> None:
    engine = engine or get_engine()
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine=None) -> Iterator[Session]:
    engine = engine or get_engine()
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
