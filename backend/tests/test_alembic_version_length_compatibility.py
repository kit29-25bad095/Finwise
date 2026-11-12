import re
from pathlib import Path
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql, sqlite
from alembic.config import Config
from alembic import command
from alembic.ddl.impl import DefaultImpl
from app.core.alembic_utils import patch_alembic_version_table, ensure_version_column_capacity
from app.core.config import settings


def test_revision_ids_length_audit():
    """
    Verifies that all revision IDs across migrations 001-007 are accounted for,
    confirms that revisions 006 (38 chars) and 007 (34 chars) exceed standard VARCHAR(32),
    and asserts that all fit safely within VARCHAR(128).
    """
    versions_dir = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    migration_files = sorted(versions_dir.glob("*.py"))
    assert len(migration_files) >= 7, "Migrations 001 through 007 must exist"

    revisions = {}
    for p in migration_files:
        txt = p.read_text(encoding="utf-8")
        rev_match = re.search(r"revision:\s*str\s*=\s*['\"]([^'\"]+)['\"]", txt)
        if rev_match:
            rev_id = rev_match.group(1)
            revisions[p.name] = rev_id

    # Verify specific revisions
    rev_006 = revisions["006_tenant_financial_history_retention.py"]
    rev_007 = revisions["007_phase5_forensic_investigations.py"]

    assert rev_006 == "006_tenant_financial_history_retention"
    assert len(rev_006) == 38, f"Revision 006 length must be 38, got {len(rev_006)}"
    assert len(rev_006) > 32, "Revision 006 exceeds VARCHAR(32)"

    assert rev_007 == "007_phase5_forensic_investigations"
    assert len(rev_007) == 34, f"Revision 007 length must be 34, got {len(rev_007)}"
    assert len(rev_007) > 32, "Revision 007 exceeds VARCHAR(32)"

    # All revisions must fit comfortably within VARCHAR(128)
    for file_name, rev_id in revisions.items():
        assert len(rev_id) <= 128, f"Revision {rev_id} in {file_name} exceeds VARCHAR(128)"


def test_version_table_ddl_compilation_postgresql():
    """
    Verifies that patch_alembic_version_table produces a Table object with
    VARCHAR(128) for version_num when compiled against PostgreSQL dialect.
    """
    patch_alembic_version_table(128)

    pg_dialect = postgresql.dialect()
    impl_cls = DefaultImpl.get_by_dialect(pg_dialect)
    impl_inst = impl_cls(pg_dialect, None, False, False, None, {})

    vt = impl_inst.version_table_impl(
        version_table="alembic_version",
        version_table_schema=None,
        version_table_pk=True,
    )

    ddl_str = str(CreateTable(vt).compile(dialect=pg_dialect))
    assert "VARCHAR(128)" in ddl_str, f"PostgreSQL DDL must use VARCHAR(128): {ddl_str}"
    assert "version_num" in ddl_str
    assert "alembic_version_pkc" in ddl_str


def test_version_table_ddl_compilation_sqlite():
    """
    Verifies that patch_alembic_version_table produces a Table object with
    VARCHAR(128) for version_num when compiled against SQLite dialect.
    """
    patch_alembic_version_table(128)

    sqlite_dialect = sqlite.dialect()
    impl_cls = DefaultImpl.get_by_dialect(sqlite_dialect)
    impl_inst = impl_cls(sqlite_dialect, None, False, False, None, {})

    vt = impl_inst.version_table_impl(
        version_table="alembic_version",
        version_table_schema=None,
        version_table_pk=True,
    )

    ddl_str = str(CreateTable(vt).compile(dialect=sqlite_dialect))
    assert "VARCHAR(128)" in ddl_str, f"SQLite DDL must use VARCHAR(128): {ddl_str}"
    assert "version_num" in ddl_str


def test_fresh_migration_from_001_through_007(tmp_path, monkeypatch):
    """
    Executes a fresh upgrade from revision 001 through 007 on an isolated disposable SQLite database:
    1. Verifies alembic_version is created with VARCHAR(128).
    2. Verifies migrations 001-007 all succeed sequentially.
    3. Verifies final version_num recorded is '007_phase5_forensic_investigations' (34 chars).
    """
    db_file = tmp_path / "fresh_migration.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setattr(settings, "SYNC_DATABASE_URL", db_url)

    alembic_cfg = Config("alembic.ini")

    # Run upgrade from 001 to head (007)
    command.upgrade(alembic_cfg, "head")

    eng = create_engine(db_url)
    with eng.connect() as conn:
        # Check column definition in SQLite pragma
        cols = conn.execute(text("PRAGMA table_info('alembic_version')")).fetchall()
        version_col = [c for c in cols if c[1] == "version_num"]
        assert len(version_col) == 1, "alembic_version.version_num column must exist"
        assert "128" in version_col[0][2], f"Column type must be VARCHAR(128), got {version_col[0][2]}"

        # Check recorded version
        current_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert current_rev == "007_phase5_forensic_investigations"
        assert len(current_rev) == 34
    eng.dispose()


def test_stepwise_recording_revisions_005_006_007(tmp_path, monkeypatch):
    """
    Tests stepwise migration progression through 005 -> 006 -> 007 to ensure
    that long revisions 006 (38 chars) and 007 (34 chars) are recorded without error.
    """
    db_file = tmp_path / "stepwise_migration.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setattr(settings, "SYNC_DATABASE_URL", db_url)

    alembic_cfg = Config("alembic.ini")

    # 1. Upgrade to 005
    command.upgrade(alembic_cfg, "005_phase4_evidence_and_lineage")
    eng = create_engine(db_url)
    with eng.connect() as conn:
        rev_005 = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert rev_005 == "005_phase4_evidence_and_lineage"
    eng.dispose()

    # 2. Upgrade to 006 (38 chars - previously failed on PostgreSQL VARCHAR(32))
    command.upgrade(alembic_cfg, "006_tenant_financial_history_retention")
    eng = create_engine(db_url)
    with eng.connect() as conn:
        rev_006 = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert rev_006 == "006_tenant_financial_history_retention"
        assert len(rev_006) == 38
    eng.dispose()

    # 3. Upgrade to 007 (34 chars)
    command.upgrade(alembic_cfg, "007_phase5_forensic_investigations")
    eng = create_engine(db_url)
    with eng.connect() as conn:
        rev_007 = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert rev_007 == "007_phase5_forensic_investigations"
        assert len(rev_007) == 34
    eng.dispose()
