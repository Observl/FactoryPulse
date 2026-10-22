"""Isolate every test from the operator's configured or default database."""
import os
import tempfile
from pathlib import Path
import pytest

# Developer shells may inherit the real identity configuration from start-local.ps1.
# Unit/regression tests must never authenticate against or mutate the operator's D1.
os.environ.pop("FACTORYPULSE_IDENTITY_CONFIG",None)
os.environ.pop("FACTORYPULSE_DEPLOYMENT",None)

_test_runtime=tempfile.TemporaryDirectory(prefix="factorypulse-tests-",dir=Path(__file__).resolve().parent)
os.environ["FACTORYPULSE_AUTH_REQUIRED"]="0"
os.environ["FACTORYPULSE_TEST_ALLOW_ANONYMOUS"]="1"
os.environ["FACTORYPULSE_ENABLE_LEGACY_FIXTURES"]="1"
os.environ["FACTORYPULSE_DATA_DIR"]=str(Path(_test_runtime.name))


@pytest.fixture(autouse=True)
def isolated_records(monkeypatch):
    from backend import main
    with main.connect() as connection:
        for table in ("auth_onboarding","records","settings","alerts","work_orders","audit_events","operation_requests","prediction_runs","import_jobs","dataset_versions","archived_records","maintenance_events","inventory_stock","inventory_reservations","inventory_movements","planning_runs","auth_users","auth_sessions","auth_attempts"):
            connection.execute(f"DELETE FROM {table}")
    main._analytics_cache.update(key=None,devices={},summary={})
    monkeypatch.setattr(main,"_api_key","")
    monkeypatch.setattr(main,"_credential_secure",False)
