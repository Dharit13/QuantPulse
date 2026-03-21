"""Add error_events table for error tracking.

Revision ID: 002_error_events
Revises: 001_baseline
Create Date: 2026-03-21
"""
from collections.abc import Sequence

from alembic import op

revision: str = "002_error_events"
down_revision: str | None = "001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS error_events (
            id BIGSERIAL PRIMARY KEY,
            timestamp TIMESTAMPTZ DEFAULT NOW(),
            level TEXT DEFAULT 'ERROR',
            error_type TEXT NOT NULL,
            message TEXT NOT NULL,
            stack_trace TEXT,
            request_path TEXT,
            request_method TEXT,
            strategy TEXT,
            occurrence_count INT DEFAULT 1,
            first_seen TIMESTAMPTZ DEFAULT NOW(),
            last_seen TIMESTAMPTZ DEFAULT NOW(),
            resolved BOOLEAN DEFAULT FALSE
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_errors_unresolved ON error_events(resolved, last_seen DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_errors_type ON error_events(error_type);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_errors_type;")
    op.execute("DROP INDEX IF EXISTS idx_errors_unresolved;")
    op.execute("DROP TABLE IF EXISTS error_events;")
