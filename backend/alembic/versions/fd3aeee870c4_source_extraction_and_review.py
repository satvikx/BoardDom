"""source extraction and review

Revision ID: fd3aeee870c4
Revises: a8d4aebbd5ea
"""

import sqlalchemy as sa

from alembic import op

revision = "fd3aeee870c4"
down_revision = "a8d4aebbd5ea"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("source_documents", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "extraction_status", sa.String(length=20), server_default="uploaded", nullable=False
            )
        )
        batch_op.add_column(sa.Column("extraction_error_code", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("extraction_error_message", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("extraction_warnings", sa.JSON(), server_default="[]", nullable=False)
        )
        batch_op.add_column(sa.Column("extracted_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column("content_revision", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(sa.Column("extraction_attempt_id", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("extraction_started_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("extraction_finished_at", sa.DateTime(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_source_documents_extraction_status"), ["extraction_status"], unique=False
        )
        batch_op.create_unique_constraint("uq_extraction_attempt", ["extraction_attempt_id"])
        batch_op.create_foreign_key("fk_source_reviewer", "users", ["reviewed_by_user_id"], ["id"])

    op.create_table(
        "source_units",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("corrected_text", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "position"),
    )
    with op.batch_alter_table("source_units", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_source_units_document_id"), ["document_id"], unique=False
        )


def downgrade():
    op.drop_table("source_units")
    with op.batch_alter_table("source_documents", schema=None) as batch_op:
        batch_op.drop_constraint("fk_source_reviewer", type_="foreignkey")
        batch_op.drop_constraint("uq_extraction_attempt", type_="unique")
        batch_op.drop_index(batch_op.f("ix_source_documents_extraction_status"))
        batch_op.drop_column("extraction_finished_at")
        batch_op.drop_column("extraction_started_at")
        batch_op.drop_column("extraction_attempt_id")
        batch_op.drop_column("content_revision")
        batch_op.drop_column("reviewed_by_user_id")
        batch_op.drop_column("reviewed_at")
        batch_op.drop_column("extracted_at")
        batch_op.drop_column("extraction_warnings")
        batch_op.drop_column("extraction_error_message")
        batch_op.drop_column("extraction_error_code")
        batch_op.drop_column("extraction_status")
