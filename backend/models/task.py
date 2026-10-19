"""SQLAlchemy model for the persistent task store."""
from sqlalchemy import (
    Boolean, Column, DateTime, Index, Integer, String, func,
)

from database import Base
from utils.crypto import EncryptedJSON, EncryptedText


class Task(Base):
    """Persistent task record. Replaces the per-process in-memory dict."""

    __tablename__ = "tasks"

    task_id = Column(String(255), primary_key=True)
    client_id = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False)
    progress = Column(Integer, nullable=False, default=0)
    message = Column(EncryptedText, nullable=False, default="")
    task_type = Column(String(64), nullable=False, default="generic")
    metadata_json = Column(EncryptedJSON, nullable=False, default=dict)
    result_data = Column(EncryptedJSON, nullable=True)
    is_cancelled = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_tasks_client_id_created_at",
            "client_id",
            created_at.desc(),
        ),
    )
