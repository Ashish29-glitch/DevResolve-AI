"""
DevResolve AI - SQLAlchemy Database Models
"""
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Boolean,
    DateTime, ForeignKey, Enum as SAEnum
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
import enum

from src.config import get_settings

settings = get_settings()
settings.database_file.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    echo=False
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── Enums ───────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    manager = "manager"
    developer = "developer"


class DevRole(str, enum.Enum):
    frontend = "frontend"
    backend = "backend"
    database = "database"
    devops = "devops"
    qa = "qa"
    fullstack = "fullstack"
    mobile = "mobile"
    unassigned = "unassigned"


class AccessStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class TicketStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"


class TicketPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class TicketTeam(str, enum.Enum):
    frontend = "frontend"
    backend = "backend"
    database = "database"
    devops = "devops"
    qa = "qa"
    fullstack = "fullstack"
    mobile = "mobile"


# ─── Models ──────────────────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False)
    description = Column(Text, default="")
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    manager = relationship("User", foreign_keys=[manager_id], back_populates="managed_projects")
    members = relationship("User", foreign_keys="User.project_id", back_populates="project")
    access_requests = relationship("AccessRequest", back_populates="project")
    tickets = relationship("Ticket", back_populates="project")
    documents = relationship("Document", back_populates="project")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole), default=UserRole.developer, nullable=False)
    dev_role = Column(SAEnum(DevRole), default=DevRole.unassigned)
    google_id = Column(String(255), unique=True, nullable=True)
    password_hash = Column(String(255), nullable=True)
    otp_secret = Column(String(100), nullable=True)
    otp_expires_at = Column(DateTime, nullable=True)
    is_approved = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    avatar_url = Column(String(500), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    project = relationship("Project", foreign_keys=[project_id], back_populates="members")
    managed_projects = relationship("Project", foreign_keys=[Project.manager_id], back_populates="manager")
    access_requests = relationship("AccessRequest", back_populates="developer")
    raised_tickets = relationship("Ticket", foreign_keys="Ticket.raised_by_id", back_populates="raised_by")
    ticket_assignments = relationship("TicketAssignment", back_populates="developer")
    daily_updates = relationship("DailyUpdate", back_populates="developer")
    uploaded_documents = relationship("Document", back_populates="uploader")


class AccessRequest(Base):
    __tablename__ = "access_requests"
    id = Column(Integer, primary_key=True, index=True)
    developer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    status = Column(SAEnum(AccessStatus), default=AccessStatus.pending)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    reviewed_at = Column(DateTime, nullable=True)

    developer = relationship("User", back_populates="access_requests")
    project = relationship("Project", back_populates="access_requests")


class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    raised_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    assigned_team = Column(SAEnum(TicketTeam), nullable=False)
    priority = Column(SAEnum(TicketPriority), default=TicketPriority.medium)
    status = Column(SAEnum(TicketStatus), default=TicketStatus.open)
    ai_solution = Column(Text, nullable=True)
    ai_route = Column(String(100), nullable=True)
    ai_sources = Column(Text, nullable=True)   # JSON
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    raised_by = relationship("User", foreign_keys=[raised_by_id], back_populates="raised_tickets")
    project = relationship("Project", back_populates="tickets")
    assignments = relationship("TicketAssignment", back_populates="ticket")


class TicketAssignment(Base):
    __tablename__ = "ticket_assignments"
    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    developer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_accepted = Column(Boolean, default=False)
    accepted_at = Column(DateTime, nullable=True)
    remark = Column(Text, nullable=True)
    remark_locked = Column(Boolean, default=False)  # locked after manager approves
    is_resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    ticket = relationship("Ticket", back_populates="assignments")
    developer = relationship("User", back_populates="ticket_assignments")


class DailyUpdate(Base):
    __tablename__ = "daily_updates"
    id = Column(Integer, primary_key=True, index=True)
    developer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    developer = relationship("User", back_populates="daily_updates")


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(500), nullable=False)
    original_name = Column(String(500), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    chunks_indexed = Column(Integer, default=0)
    file_size = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="documents")
    uploader = relationship("User", back_populates="uploaded_documents")


def init_db():
    """Create all tables and seed default data."""
    Base.metadata.create_all(bind=engine)
    _seed_default_data()


def _seed_default_data():
    """Seed default projects and manager accounts."""
    db = SessionLocal()
    try:
        from src.auth.hash import hash_password

        # Create default projects
        default_projects = [
            {"name": "DevResolve Platform", "description": "Main DevResolve AI platform development"},
            {"name": "Mobile App", "description": "Mobile application development"},
            {"name": "API Gateway", "description": "Backend API gateway project"},
            {"name": "Data Pipeline", "description": "Data engineering and ETL pipelines"},
        ]

        for proj_data in default_projects:
            existing = db.query(Project).filter(Project.name == proj_data["name"]).first()
            if not existing:
                proj = Project(**proj_data)
                db.add(proj)

        db.commit()

        # Create default manager account
        manager_email = "admin@devresolve.ai"
        existing_manager = db.query(User).filter(User.email == manager_email).first()
        if not existing_manager:
            project = db.query(Project).filter(Project.name == "DevResolve Platform").first()
            manager = User(
                email=manager_email,
                name="System Manager",
                role=UserRole.manager,
                password_hash=hash_password("Admin@123"),
                is_approved=True,
                is_active=True,
                project_id=project.id if project else None,
            )
            db.add(manager)
            db.flush()
            if project:
                project.manager_id = manager.id
            db.commit()
        else:
            # ensure password hash is updated cleanly
            existing_manager.password_hash = hash_password("Admin@123")
            db.commit()

    except Exception as e:
        db.rollback()
        print(f"Seed error (non-fatal): {e}")
    finally:
        db.close()
