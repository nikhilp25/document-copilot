"""Application-side user record, mirrored from Supabase Auth."""

import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Table, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base, created_at_column, updated_at_column

# Supabase owns the `auth` schema. This stub exists only so `users.id` can
# declare a real foreign key to it — SQLAlchemy cannot render a reference to a
# table that is absent from the metadata. Alembic's `env.py` must exclude the
# `auth` schema from autogenerate so it never tries to create or drop this.
auth_users = Table(
    "users",
    Base.metadata,
    Column("id", Uuid, primary_key=True),
    schema="auth",
)


class User(Base):
    """One row per authenticated user.

    The primary key *is* `auth.users.id` — this table never mints its own ids.
    Supabase owns credentials and sessions; this row exists so product tables
    can hang a foreign key off a table we control, and so a deleted auth user
    cascades away their threads and messages.
    """

    __tablename__ = "users"

    # No default: the id always comes from the verified Supabase JWT.
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("auth.users.id", ondelete="CASCADE"), primary_key=True
    )
    email: Mapped[str] = mapped_column(Text, unique=True)

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
