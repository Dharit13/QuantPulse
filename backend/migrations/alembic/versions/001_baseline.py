"""Baseline — marks the existing schema (001_init.sql) as the starting point.

All tables created by 001_init.sql are assumed to already exist.
This migration is a no-op; it just establishes the Alembic version baseline.

Revision ID: 001_baseline
Revises: None
Create Date: 2026-03-21
"""

from collections.abc import Sequence

revision: str = "001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
