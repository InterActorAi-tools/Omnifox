"""Chat about one analysis (short-term memory). Encrypted; 30-day retention."""
from sqlalchemy import Column, DateTime, Index, Integer, String, func

from database import Base
from utils.crypto import EncryptedJSON


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    client_id = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False)  # user | model | proposal
    content = Column(EncryptedJSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_chat_messages_client_id_filename", "client_id", "filename"),)
