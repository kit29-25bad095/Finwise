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

    Transaction Handling:
    - In standard Alembic execution, this helper is invoked inside Alembic's migration
      transaction (`with context.begin_transaction():`), ensuring Alembic retains complete
      ownership of the migration transaction and that PostgreSQL DDL and migration version
      updates commit atomically.
    - If invoked on an idle connection outside an active transaction, any transaction started
      by SQLAlchemy's inspection query is rolled back in the finally block so that the helper
      does not leave an unintended active transaction before Alembic begins.
    """
    if connection.dialect.name == "postgresql":
        was_in_transaction = connection.in_transaction()
        try:
            insp = inspect(connection)
            if insp.has_table("alembic_version"):
                columns = insp.get_columns("alembic_version")
                needs_alter = True
                for col in columns:
                    if col.get("name") == "version_num":
                        col_type = col.get("type")
                        current_length = getattr(col_type, "length", None)
                        if current_length is not None and current_length >= length:
                            needs_alter = False
                            break
                if needs_alter:
                    connection.execute(
                        text(f"ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR({length});")
                    )
        finally:
            if not was_in_transaction and connection.in_transaction():
                connection.rollback()
