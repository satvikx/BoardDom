"""syllabus, retrieval chunks, versioned artifacts, and jobs

Revision ID: e5a7c2d9b4f1
Revises: c3b1d9e0f7a2
"""

import sqlalchemy as sa

from alembic import op

revision = "e5a7c2d9b4f1"
down_revision = "c3b1d9e0f7a2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chunk_counters",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("next_ordinal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id"),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="job_status"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.create_index(
            "ix_jobs_workspace_created", ["workspace_id", "created_at"], unique=False
        )

    op.create_table(
        "syllabi",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'approved')", name="syllabus_status"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id"),
    )
    op.create_table(
        "source_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("content_revision", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "ordinal"),
    )
    with op.batch_alter_table("source_chunks", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_source_chunks_document_id"), ["document_id"], unique=False
        )

    op.create_table(
        "syllabus_units",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("syllabus_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["syllabus_id"], ["syllabi.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("syllabus_units", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_syllabus_units_syllabus_id"), ["syllabus_id"], unique=False
        )

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=True),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["unit_id"], ["syllabus_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "kind", "unit_id"),
    )
    with op.batch_alter_table("artifacts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_artifacts_unit_id"), ["unit_id"], unique=False)

    op.create_table(
        "artifact_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("origin IN ('generated', 'edited', 'restored')", name="version_origin"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "number"),
    )
    with op.batch_alter_table("artifact_versions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_artifact_versions_artifact_id"), ["artifact_id"], unique=False
        )


def downgrade():

    with op.batch_alter_table("artifact_versions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_artifact_versions_artifact_id"))

    op.drop_table("artifact_versions")
    with op.batch_alter_table("artifacts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_artifacts_unit_id"))

    op.drop_table("artifacts")
    with op.batch_alter_table("syllabus_units", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_syllabus_units_syllabus_id"))

    op.drop_table("syllabus_units")
    with op.batch_alter_table("source_chunks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_source_chunks_document_id"))

    op.drop_table("source_chunks")
    op.drop_table("syllabi")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_jobs_workspace_created")

    op.drop_table("jobs")
    op.drop_table("chunk_counters")
