"""labs lessons concepts publishing

Revision ID: f1b3d5e7a9c2
Revises: e5a7c2d9b4f1
"""

import sqlalchemy as sa

from alembic import op

revision = "f1b3d5e7a9c2"
down_revision = "e5a7c2d9b4f1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "concepts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["unit_id"], ["syllabus_units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "key"),
    )
    op.create_table(
        "concept_edges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("prerequisite_id", sa.Uuid(), nullable=False),
        sa.Column("concept_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("prerequisite_id <> concept_id", name="no_self_edge"),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prerequisite_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prerequisite_id", "concept_id"),
    )
    with op.batch_alter_table("concept_edges", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_concept_edges_workspace_id"), ["workspace_id"], unique=False
        )

    with op.batch_alter_table("artifacts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("published_version", sa.Integer(), nullable=True))

    with op.batch_alter_table("source_chunks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("embedding_model", sa.String(length=100), server_default="", nullable=False)
        )

    with op.batch_alter_table("workspaces", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("has_lab", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )
        batch_op.add_column(sa.Column("published_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("workspaces", schema=None) as batch_op:
        batch_op.drop_column("published_at")
        batch_op.drop_column("has_lab")

    with op.batch_alter_table("source_chunks", schema=None) as batch_op:
        batch_op.drop_column("embedding_model")

    with op.batch_alter_table("artifacts", schema=None) as batch_op:
        batch_op.drop_column("published_version")

    with op.batch_alter_table("concept_edges", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_concept_edges_workspace_id"))

    op.drop_table("concept_edges")
    op.drop_table("concepts")
