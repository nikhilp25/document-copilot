"""SQLAlchemy models — the source of truth for the database schema.

One table per module, named after the table.

Alembic's `env.py` should import `Base` from here (not from `base.py`) so that
importing the metadata also imports every model module and registers its
table. A model missing from this file is a table autogenerate silently
proposes dropping.
"""

from app.database.models.base import Base
from app.database.models.chat_messages import ChatMessage, MessageRole
from app.database.models.chat_threads import ChatThread
from app.database.models.document_chunks import EMBEDDING_DIMENSIONS, DocumentChunk
from app.database.models.message_citations import MessageCitation
from app.database.models.source_documents import SourceDocument
from app.database.models.users import User, auth_users

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "Base",
    "ChatMessage",
    "ChatThread",
    "DocumentChunk",
    "MessageCitation",
    "MessageRole",
    "SourceDocument",
    "User",
    "auth_users",
]
