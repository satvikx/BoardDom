"""roles, account management, and enrollments

Revision ID: c3b1d9e0f7a2
Revises: fd3aeee870c4

Every existing user becomes a teacher. On SQLite, batch mode rebuilds the users
table; alembic/env.py disables foreign keys for the migration connection so the
rebuild's DROP TABLE does not cascade into sessions/workspaces, and verifies
foreign keys before committing.

Downgrade drops enrollments and the role columns. Admin and student accounts then
become ordinary accounts; remove them first if that matters.
"""

import sqlalchemy as sa

from alembic import op

revision = "c3b1d9e0f7a2"
down_revision = "fd3aeee870c4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("role", sa.String(length=20), server_default="teacher", nullable=False)
        )
        batch_op.add_column(sa.Column("created_by_user_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "must_change_password", sa.Boolean(), server_default=sa.false(), nullable=False
            )
        )
        batch_op.add_column(sa.Column("last_login_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("student_limit", sa.Integer(), nullable=True))
        batch_op.create_check_constraint("user_role", "role IN ('admin', 'teacher', 'student')")
        batch_op.create_check_constraint(
            "nonnegative_student_limit", "student_limit IS NULL OR student_limit >= 0"
        )
        batch_op.create_foreign_key(
            "fk_users_created_by", "users", ["created_by_user_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_index(
            batch_op.f("ix_users_created_by_user_id"), ["created_by_user_id"], unique=False
        )
    # Explicit, in case a dialect does not backfill the server default.
    op.execute("UPDATE users SET role = 'teacher'")

    op.create_table(
        "enrollments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "student_id"),
    )
    with op.batch_alter_table("enrollments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_enrollments_student_id"), ["student_id"], unique=False)


def downgrade():
    with op.batch_alter_table("enrollments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_enrollments_student_id"))
    op.drop_table("enrollments")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_created_by_user_id"))
        batch_op.drop_constraint("fk_users_created_by", type_="foreignkey")
        batch_op.drop_constraint("nonnegative_student_limit", type_="check")
        batch_op.drop_constraint("user_role", type_="check")
        batch_op.drop_column("student_limit")
        batch_op.drop_column("last_login_at")
        batch_op.drop_column("must_change_password")
        batch_op.drop_column("created_by_user_id")
        batch_op.drop_column("role")
