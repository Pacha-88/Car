"""Engine construction, in particular the connect_args each driver needs.

Regression coverage for a real production failure: the first live GitHub
Actions run against Supabase died with

    psycopg.errors.DuplicatePreparedStatement:
        prepared statement "_pg3_0" already exists

on 24 of 32 scrape combos. Supabase's pooler (port 6543) is PgBouncer in
transaction mode, which hands each transaction whatever server connection
is free — so psycopg3's automatic server-side PREPARE ends up re-preparing
the same statement name on a connection that already has it. Disabling
prepared statements is the documented fix.

These assert the settings rather than opening a real pooled connection
(that needs a live PgBouncer, which CI doesn't have) — but the fix itself
was verified against a real local PgBouncer in transaction mode, where it
reproduced the failure before and passed 8 consecutive scrapes plus a full
scrape-all after.
"""

from __future__ import annotations

from car_tracker.db.session import connect_args_for, get_engine, normalize_database_url

DIRECT_URL = "postgresql+psycopg://user:pw@db.abc.supabase.co:5432/postgres"
POOLER_URL = "postgresql+psycopg://user:pw@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"


def test_postgres_disables_prepared_statements():
    assert connect_args_for(POOLER_URL)["prepare_threshold"] is None


def test_direct_postgres_connection_gets_the_same_setting():
    """The check keys off the driver, not the hostname or port — a direct
    connection and the pooler are configured identically, so switching
    between them can't silently reintroduce the failure."""
    assert connect_args_for(DIRECT_URL) == connect_args_for(POOLER_URL)


def test_sqlite_keeps_its_own_connect_args():
    args = connect_args_for("sqlite:///car_tracker.db")
    assert args["check_same_thread"] is False
    # The psycopg-only knob must not leak onto a driver that rejects it.
    assert "prepare_threshold" not in args


def test_unknown_driver_gets_no_special_args():
    assert connect_args_for("mysql://user:pw@localhost/db") == {}


def test_get_engine_builds_a_working_sqlite_engine(tmp_path):
    """Guards the wiring, not just the helper: connect_args must actually
    reach create_engine in a form the driver accepts."""
    engine = get_engine(f"sqlite:///{tmp_path}/probe.db")
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT 1").scalar() == 1


# --- URL normalization -------------------------------------------------
# Regression for the first real run of scripts/scrape-local.command: the
# Supabase URL was pasted verbatim (`postgresql://`), SQLAlchemy resolved
# that to the psycopg2 dialect, and the run died at the first query with
# `ModuleNotFoundError: No module named 'psycopg2'` — a package this
# project never depends on.

SUPABASE_RAW = "postgresql://postgres.abc:pw@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"


def test_bare_postgresql_scheme_is_routed_to_psycopg3():
    assert normalize_database_url(SUPABASE_RAW).startswith("postgresql+psycopg://")


def test_normalization_preserves_everything_after_the_scheme():
    normalized = normalize_database_url(SUPABASE_RAW)
    assert normalized == "postgresql+psycopg://" + SUPABASE_RAW.removeprefix("postgresql://")


def test_legacy_postgres_alias_is_also_normalized():
    assert normalize_database_url("postgres://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"


def test_an_explicit_driver_is_left_alone():
    explicit = "postgresql+psycopg://u:p@h:5432/db"
    assert normalize_database_url(explicit) == explicit


def test_sqlite_urls_are_untouched():
    assert normalize_database_url("sqlite:///car_tracker.db") == "sqlite:///car_tracker.db"


def test_a_normalized_url_still_gets_the_pooler_safe_connect_args():
    """The two fixes must compose: normalizing the scheme is what makes
    connect_args_for recognise it as psycopg in the first place."""
    normalized = normalize_database_url(SUPABASE_RAW)
    assert connect_args_for(normalized)["prepare_threshold"] is None


def test_engine_from_a_raw_supabase_url_uses_the_psycopg3_dialect():
    """The end-to-end guard: build the engine the way the user's config
    does and assert the dialect, without connecting."""
    engine = get_engine(SUPABASE_RAW)
    assert engine.dialect.driver == "psycopg"


# --- the zero-config default -------------------------------------------
# DEFAULT_SQLITE_PATH is relative, so the database lands wherever the
# process was started. That is the zero-setup dev experience AND a footgun:
# a command run from the wrong directory without DATABASE_URL silently
# creates a fresh, empty database right there and reads as "the scrape ran
# but the dashboard is empty". A stray zero-byte car_tracker.db really did
# turn up in frontend/public/data/. The default must therefore say where
# the data actually is.


def test_defaulting_to_local_sqlite_names_the_absolute_path(tmp_path, monkeypatch, capsys):
    from car_tracker.db import session as session_module

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(session_module, "_ENGINES", {})

    session_module.get_engine()

    out = capsys.readouterr().out
    assert "DATABASE_URL not set" in out
    assert str(tmp_path) in out  # the ABSOLUTE path - naming the cwd is the point


def test_a_configured_url_stays_quiet(tmp_path, monkeypatch, capsys):
    """The notice is for the default only - a configured run printing a
    db line per process would just be noise nobody reads."""
    from car_tracker.db import session as session_module

    monkeypatch.setattr(session_module, "_ENGINES", {})
    get_engine(f"sqlite:///{tmp_path}/configured.db")
    assert "DATABASE_URL" not in capsys.readouterr().out
