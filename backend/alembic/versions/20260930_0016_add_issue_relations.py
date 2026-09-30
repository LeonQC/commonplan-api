"""add configurable issue relations

Revision ID: 20260930_0016
Revises: 20260929_0015
"""

from alembic import op


revision = "20260930_0016"
down_revision = "20260929_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE issue_relation_types (
            id VARCHAR(36) PRIMARY KEY,
            workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            key VARCHAR(64) NOT NULL,
            forward_label VARCHAR(120) NOT NULL,
            inverse_label VARCHAR(120) NOT NULL,
            category VARCHAR(24) NOT NULL DEFAULT 'custom',
            is_system BOOLEAN NOT NULL DEFAULT FALSE,
            is_symmetric BOOLEAN NOT NULL DEFAULT FALSE,
            allow_cycles BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            archived_at TIMESTAMPTZ,
            CONSTRAINT uq_issue_relation_type_key UNIQUE (workspace_id, key),
            CONSTRAINT ck_issue_relation_type_category CHECK (category IN ('dependency', 'custom'))
        );
        CREATE INDEX ix_issue_relation_types_workspace ON issue_relation_types (workspace_id);

        CREATE TABLE issue_relations (
            id VARCHAR(36) PRIMARY KEY,
            workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            relation_type_id VARCHAR(36) NOT NULL REFERENCES issue_relation_types(id) ON DELETE CASCADE,
            source_issue_id VARCHAR(36) NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
            target_issue_id VARCHAR(36) NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
            created_by_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_issue_relation_distinct CHECK (source_issue_id <> target_issue_id),
            CONSTRAINT uq_issue_relation_edge UNIQUE (relation_type_id, source_issue_id, target_issue_id)
        );
        CREATE INDEX ix_issue_relations_workspace ON issue_relations (workspace_id);
        CREATE INDEX ix_issue_relations_source ON issue_relations (source_issue_id);
        CREATE INDEX ix_issue_relations_target ON issue_relations (target_issue_id);

        INSERT INTO issue_relation_types (
            id, workspace_id, key, forward_label, inverse_label,
            category, is_system, is_symmetric, allow_cycles
        )
        SELECT
            gen_random_uuid()::text, id, defaults.key, defaults.forward_label,
            defaults.inverse_label, defaults.category, TRUE,
            defaults.is_symmetric, defaults.allow_cycles
        FROM workspaces
        CROSS JOIN (VALUES
            ('blocked_by', 'is blocked by', 'blocks', 'dependency', FALSE, FALSE),
            ('relates_to', 'relates to', 'relates to', 'custom', TRUE, TRUE),
            ('action_item_of', 'is an action item of', 'has action item', 'custom', FALSE, TRUE)
        ) AS defaults(key, forward_label, inverse_label, category, is_symmetric, allow_cycles);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE issue_relations;
        DROP TABLE issue_relation_types;
        """
    )
