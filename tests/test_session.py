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

from car_tracker.db.session import connect_args_for, get_engine

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
