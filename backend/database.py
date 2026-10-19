import logging
from contextlib import contextmanager
from typing import Callable, TypeVar

from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import settings  # ← Use main config

logger = logging.getLogger(__name__)

# SQLite-specific connection args
connect_args = {"check_same_thread": False} if "sqlite" in settings.database_url else {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Arbitrary fixed key for the bootstrap advisory lock. Any 64-bit signed int
# works; this one is just `hash("omnicat-bootstrap") & 0x7fff_ffff_ffff_ffff`
# pinned so all workers compute the same value without re-running hash().
_BOOTSTRAP_LOCK_KEY = 4823917562012345671

_is_postgres = settings.database_url.startswith(("postgres", "postgresql"))


T = TypeVar("T")


@contextmanager
def bootstrap_lock():
    """Serialize startup-time schema + seed work across gunicorn workers.

    Uses pg_advisory_lock on Postgres so only one worker at a time runs
    DDL / seed inserts; others block until the holder releases, then see
    the work already done and proceed. On SQLite this is a no-op (single
    writer at the filesystem level already serializes).

    The lock is session-scoped: it's released when the connection is
    returned to the pool, even if an exception fires.
    """
    if not _is_postgres:
        yield
        return

    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _BOOTSTRAP_LOCK_KEY})
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _BOOTSTRAP_LOCK_KEY})


def run_with_bootstrap_lock(fn: Callable[[], T]) -> T:
    """Convenience: call fn() inside the bootstrap_lock context."""
    with bootstrap_lock():
        return fn()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations():
    """Bring the schema to the latest Alembic revision. Safe to call
    repeatedly; wrap in bootstrap_lock() when several workers start."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parent / "alembic.ini"))
    cfg.attributes["configure_logger"] = False  # keep the app's logging setup
    command.upgrade(cfg, "head")
    logger.info("✅ Database migrated to latest revision")


def init_db():
    """Create tables straight from the models (test fixtures only).
    The app and CLI use run_migrations()."""
    import models  # noqa: F401 - load all model metadata before create_all
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables created/verified")


def drop_db():
    Base.metadata.drop_all(bind=engine)
    logger.warning("⚠️  All tables dropped")