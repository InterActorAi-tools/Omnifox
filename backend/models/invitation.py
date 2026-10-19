from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from database import Base

class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(255), unique=True, index=True, nullable=False)

    email = Column(String(255), nullable=False) 
    name = Column(String(255), nullable=False)

    role = Column(String(50), default="basic_user") # The role the new user will get
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_used = Column(Boolean, default=False)
    created_by = Column(Integer, nullable=True) # ID of admin who created it
    created_at = Column(DateTime(timezone=True), server_default=func.now())