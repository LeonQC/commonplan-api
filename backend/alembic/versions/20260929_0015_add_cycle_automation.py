"""add repeating cycle settings and completion tracking

Revision ID: 20260929_0015
Revises: 20260929_0014
"""

from alembic import op


revision = "20260929_0015"
down_revision = "20260929_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cycles ADD COLUMN completed_at TIMESTAMPTZ;")
    op.execute(
        """
        CREATE TABLE team_cycle_settings (
            team_id VARCHAR(36) PRIMARY KEY REFERENCES teams(id) ON DELETE CASCADE,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            duration_weeks SMALLINT NOT NULL DEFAULT 2,
            upcoming_cycle_count SMALLINT NOT NULL DEFAULT 3,
            next_cycle_starts_on DATE,
            rollover_incomplete BOOLEAN NOT NULL DEFAULT TRUE,
            updated_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_team_cycle_duration CHECK (duration_weeks BETWEEN 1 AND 8),
            CONSTRAINT ck_team_cycle_upcoming CHECK (upcoming_cycle_count BETWEEN 1 AND 15)
        );
        """
    )
    op.execute(
        """
        INSERT INTO team_cycle_settings (team_id)
        SELECT id FROM teams;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE team_cycle_settings;")
    op.execute("ALTER TABLE cycles DROP COLUMN completed_at;")
