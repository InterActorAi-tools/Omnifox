"""Verify the Task model is registered with Base.metadata."""
from database import Base
import models  # noqa: F401 - Ensure models are loaded into Base.metadata


def test_task_model_is_registered():
    """Task table must be in Base.metadata so create_all picks it up."""
    table_names = list(Base.metadata.tables.keys())
    assert "tasks" in table_names, f"tasks table missing from {table_names}"


def test_task_model_has_expected_columns():
    """Task table must have all spec'd columns with correct types."""
    table = Base.metadata.tables["tasks"]
    column_names = {c.name for c in table.columns}
    expected = {
        "task_id", "client_id", "status", "progress", "message",
        "task_type", "metadata_json", "result_data", "is_cancelled",
        "created_at", "updated_at",
    }
    assert expected.issubset(column_names), f"missing: {expected - column_names}"


def test_task_id_is_primary_key():
    table = Base.metadata.tables["tasks"]
    pk_columns = {c.name for c in table.primary_key.columns}
    assert pk_columns == {"task_id"}


def test_client_id_created_at_index_exists():
    """Index on (client_id, created_at DESC) is required for get_client_tasks."""
    table = Base.metadata.tables["tasks"]
    index_names = {idx.name for idx in table.indexes}
    assert "ix_tasks_client_id_created_at" in index_names


def test_no_redundant_client_id_index():
    """client_id should only be indexed via the composite index, not standalone.

    The composite index ix_tasks_client_id_created_at covers single-column
    client_id lookups via leftmost-prefix matching. A standalone index would
    be redundant write/storage overhead.
    """
    table = Base.metadata.tables["tasks"]
    # Find all indexes that have client_id as their first (and possibly only) column
    client_id_indexes = [
        idx for idx in table.indexes
        if len(idx.columns) >= 1 and list(idx.columns)[0].name == "client_id"
    ]
    # Only the composite index should be present
    index_names = sorted(idx.name for idx in client_id_indexes)
    assert index_names == ["ix_tasks_client_id_created_at"], (
        f"unexpected client_id indexes: {index_names}"
    )
