from typing import Any
from alembic.ddl.impl import DefaultImpl
from sqlalchemy import (
    Table,
    MetaData,
    Column,
    String,
    PrimaryKeyConstraint,
    inspect,
    text,
)


def patch_alembic_version_table(length: int = 128) -> None:
    """
    Overrides Alembic DefaultImpl.version_table_impl to generate version_num as
    VARCHAR(length) instead of standard VARCHAR(32).

    This prevents PostgreSQL StringDataRightTruncation errors on descriptive revisions
    such as:
      - 006_tenant_financial_history_retention (38 chars)
      - 007_phase5_forensic_investigations (34 chars)
    """
    def _widen_version_table_impl(
        self,
        *,
        version_table: str,
        version_table_schema: str | None,
        version_table_pk: bool,
        **kw: Any,
    ) -> Table:
        vt = Table(
            version_table,
            MetaData(),
            Column("version_num", String(length), nullable=False),
            schema=version_table_schema,
        )
        if version_table_pk:
            vt.append_constraint(
                PrimaryKeyConstraint("version_num", name=f"{version_table}_pkc")
            )
        return vt

    DefaultImpl.version_table_impl = _widen_version_table_impl


def ensure_version_column_capacity(connection, length: int = 128) -> None:
    """
    If alembic_version table already exists with a narrower version_num column (e.g. VARCHAR(32)),
    widens it to VARCHAR(length) on PostgreSQL.
    """
    if connection.dialect.name == "postgresql":
        insp = inspect(connection)
        if insp.has_table("alembic_version"):
            connection.execute(
                text(f"ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR({length});")
            )
