"""SQLAlchemy model for the shared URL extraction cache."""
from sqlalchemy import Boolean, Column, Float, Integer, String

from database import Base
from utils.crypto import EncryptedJSON, EncryptedText


class UrlCacheEntry(Base):
    """One user's cached URL extraction, shared by every Gunicorn worker.
    Entries are per user: one user's results are never served to another."""

    __tablename__ = "url_cache"

    url_hash = Column(String(64), primary_key=True)
    client_id = Column(String(255), nullable=False, index=True)
    url = Column(EncryptedText, nullable=False)
    project = Column(String(255), nullable=False)
    extracted_filename = Column(String(255), nullable=False)
    processed_filename = Column(String(255), nullable=True)
    comments_count = Column(Integer, nullable=False, default=0)
    sentiment_data = Column(EncryptedJSON, nullable=True)
    is_processed = Column(Boolean, nullable=False, default=False)
    # Epoch seconds, matching the previous JSON cache format.
    created_at = Column(Float, nullable=False, index=True)
    last_accessed = Column(Float, nullable=False)
