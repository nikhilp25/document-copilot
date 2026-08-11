"""Declarative base and shared column helpers.

These models exist primarily to describe the schema for Alembic autogenerate.
Runtime data access goes through the Supabase client and hand-written SQL for
retrieval, so there are deliberately no `relationship()` definitions here.
"""

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, MappedColumn, mapped_column

# Deterministic constraint/index names so Alembic autogenerate produces stable
# migrations instead of relying on Postgres-assigned names.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def created_at_column() -> MappedColumn[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def updated_at_column() -> MappedColumn[datetime]:
    # `onupdate` only fires on SQLAlchemy writes. Rows written through the
    # Supabase client must set this column themselves.
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
