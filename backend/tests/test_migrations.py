"""Alembic migrations must build the schema the models describe (D7)."""
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

BACKEND = Path(__file__).resolve().parent.parent


def test_migrations_match_models(tmp_path, monkeypatch):
    import database
    import models  # noqa: F401  (registers every table)

    engine = create_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    monkeypatch.setattr(database, "engine", engine)

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), database.Base.metadata)
    assert diff == [], f"models changed without a migration: {diff}"
    engine.dispose()
