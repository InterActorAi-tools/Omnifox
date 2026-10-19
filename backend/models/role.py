from sqlalchemy import Column, Integer, String, Table, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

# Many-to-Many: Roles ↔ Permissions
role_permissions = Table(
    'role_permissions',
    Base.metadata,
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    Column('permission_id', Integer, ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)
)

# Many-to-Many: Users ↔ Roles
user_roles = Table(
    'user_roles',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True)
)

class Role(Base):
    __tablename__ = "roles"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)  # admin, dashboard_user, basic_user
    description = Column(String(255), nullable=True)
    
    # Relationships
    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")
    users = relationship("User", secondary=user_roles, back_populates="roles")
    
    def __repr__(self):
        return f"<Role {self.name}>"

class Permission(Base):
    __tablename__ = "permissions"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)  # view_dashboard, manage_users
    description = Column(String(255), nullable=True)
    
    # Relationships
    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")
    
    def __repr__(self):
        return f"<Permission {self.name}>"