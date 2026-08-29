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


def normalize_database_url(url: str) -> str:
    """Accept a Postgres connection string exactly as a provider hands it over.

    Supabase (and every other hosted Postgres) gives you a URL starting
    `postgresql://`. SQLAlchemy maps that bare scheme to the **psycopg2**
    dialect — a driver this project deliberately doesn't install, since it
    uses psycopg 3 — so the first query dies with
    `ModuleNotFoundError: No module named 'psycopg2'`, long after the run
    looked like it was working.

    Requiring people to hand-edit the scheme is a step that will be
    forgotten (it was, on the first real run of scripts/scrape-local.*),
    and the failure it produces names a package nobody asked for. Rewrite
    it here instead, once, for every entry point.
    """
    for prefix in ("postgresql://", "postgres://"):  # postgres:// is the older Heroku-style alias
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def connect_args_for(url: str) -> dict[str, object]:
    """Driver-specific connection settings for a database URL.

    Split out from get_engine() so it can be asserted directly: SQLAlchemy
    bakes connect_args into the engine at construction, so there's no way
    to read them back off a built engine.
    """
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    if "psycopg" in url:
        # prepare_threshold=None disables psycopg3's automatic server-side
        # PREPARE. Required when connecting through a transaction-mode
        # connection pooler (PgBouncer, which is what Supabase's pooler on
        # port 6543 runs): the pooler hands each transaction whatever server
        # connection is free, so a statement prepared on one connection is
        # then re-prepared under the same name on another, and Postgres
        # rejects it with DuplicatePreparedStatement. Cheap insurance on a
        # direct connection too — this project's queries run once per
        # listing per day, far too infrequently for prepared statements to
        # pay for themselves.
        return {"prepare_threshold": None}
    return {}


# One engine (and thus one connection pool) per database URL, for the life
# of the process. session_scope() used to build a fresh engine per call,
# which meant every combo of a scrape opened its own TCP+TLS+auth handshake
# to Supabase and threw the connection away afterwards - pure overhead, and
# it also defeats SQLAlchemy's pooling entirely.
_ENGINES: dict[str, object] = {}


def get_engine(database_url: str | None = None):
    raw = database_url or os.environ.get("DATABASE_URL") or f"sqlite:///{DEFAULT_SQLITE_PATH}"
    url = normalize_database_url(raw)
    engine = _ENGINES.get(url)
    if engine is None:
        engine = _ENGINES[url] = create_engine(url, connect_args=connect_args_for(url))
    return engine


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
