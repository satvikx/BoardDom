"""wizard sources research guardrails evals

Revision ID: b3d5f7a9c1e2
Revises: a2c4e6f8b0d1
"""

import sqlalchemy as sa

from alembic import op

revision = "b3d5f7a9c1e2"
down_revision = "a2c4e6f8b0d1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="eval_status"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("pipeline", sa.String(length=20), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Double(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ai_calls", schema=None) as batch_op:
        batch_op.create_index("ix_ai_calls_user_created", ["user_id", "created_at"], unique=False)
        batch_op.create_index("ix_ai_calls_workspace", ["workspace_id"], unique=False)

    op.create_table(
        "course_profiles",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("audience", sa.String(length=200), nullable=False),
        sa.Column("weeks", sa.Integer(), nullable=False),
        sa.Column("hours_per_week", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("lab_hours_per_week", sa.Integer(), nullable=False),
        sa.Column("experiments", sa.Integer(), nullable=False),
        sa.Column("must_include", sa.JSON(), nullable=False),
        sa.Column("exclude", sa.JSON(), nullable=False),
        sa.Column("assessment", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("mode IN ('theory', 'theory_lab')", name="course_mode"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_table(
        "research_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("flagged", sa.Boolean(), nullable=False),
        sa.Column("flag_reason", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'ignored')", name="finding_status"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "ordinal"),
    )
    with op.batch_alter_table("source_chunks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("flagged", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )

    with op.batch_alter_table("syllabus_units", schema=None) as batch_op:
        batch_op.add_column(sa.Column("weeks", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("citations", sa.JSON(), server_default="{}", nullable=False))


def downgrade():
    with op.batch_alter_table("syllabus_units", schema=None) as batch_op:
        batch_op.drop_column("citations")
        batch_op.drop_column("weeks")

    with op.batch_alter_table("source_chunks", schema=None) as batch_op:
        batch_op.drop_column("flagged")

    op.drop_table("research_findings")
    op.drop_table("course_profiles")
    with op.batch_alter_table("ai_calls", schema=None) as batch_op:
        batch_op.drop_index("ix_ai_calls_workspace")
        batch_op.drop_index("ix_ai_calls_user_created")

    op.drop_table("ai_calls")
    op.drop_table("eval_runs")
