import sqlite3
from contextlib import closing

import pytest

from backend import main,migrations
from tests.test_api import client


def test_schema_initialization_is_versioned_and_repeatable():
    main.init();main.init()
    with main.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0]==migrations.SCHEMA_VERSION
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=?",(migrations.SCHEMA_VERSION,)).fetchone()[0]==1
    assert client.get("/api/health/ready").json()["database_read_write"] is True


def test_newer_database_is_rejected_before_any_migration():
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute("PRAGMA user_version=999")
        with pytest.raises(RuntimeError):migrations.check_compatible(connection)
        assert connection.execute("PRAGMA user_version").fetchone()[0]==999
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]==0


def test_incomplete_schema_cannot_be_marked_current():
    with closing(sqlite3.connect(":memory:")) as connection:
        with pytest.raises(RuntimeError):migrations.finalize_schema(connection,0)
        assert connection.execute("PRAGMA user_version").fetchone()[0]==0
