"""Track background job runs so a scheduler that only makes HTTP calls (AWS EventBridge) can run due jobs.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE job_runs (
      name              text PRIMARY KEY,
      last_finished_at  timestamptz NOT NULL,
      last_result       text
    );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_runs;")
