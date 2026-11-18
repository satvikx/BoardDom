"""student portal coach quizzes videos

Revision ID: a2c4e6f8b0d1
Revises: f1b3d5e7a9c2
"""

import sqlalchemy as sa

from alembic import op

revision = "a2c4e6f8b0d1"
down_revision = "f1b3d5e7a9c2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("in_scope", sa.Boolean(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("checklist", sa.JSON(), nullable=False),
        sa.Column("known", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("role IN ('student', 'coach')", name="chat_role"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("chat_messages", schema=None) as batch_op:
        batch_op.create_index(
            "ix_chat_course_student", ["workspace_id", "student_id", "created_at"], unique=False
        )

    op.create_table(
        "quizzes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=True),
        sa.Column("difficulty", sa.String(length=10), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("difficulty IN ('easy', 'medium', 'hard')", name="quiz_difficulty"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unit_id"], ["syllabus_units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("quizzes", schema=None) as batch_op:
        batch_op.create_index(
            "ix_quizzes_course_student", ["workspace_id", "student_id", "created_at"], unique=False
        )

    op.create_table(
        "study_aids",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("tool", sa.String(length=20), nullable=False),
        sa.Column("notes_version", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "tool IN ('mind_map', 'short_notes', 'flashcards')", name="study_aid_tool"
        ),
        sa.ForeignKeyConstraint(["unit_id"], ["syllabus_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("unit_id", "tool", "notes_version"),
    )
    with op.batch_alter_table("study_aids", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_study_aids_workspace_id"), ["workspace_id"], unique=False
        )

    op.create_table(
        "unit_progress",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unit_id"], ["syllabus_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", "unit_id"),
    )
    with op.batch_alter_table("unit_progress", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_unit_progress_unit_id"), ["unit_id"], unique=False)

    op.create_table(
        "videos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("notes_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("has_audio", sa.Boolean(), nullable=False),
        sa.Column("storage_key", sa.String(length=32), nullable=True),
        sa.Column("duration_seconds", sa.Double(), nullable=True),
        sa.Column("slide_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'ready', 'failed')", name="video_status"
        ),
        sa.ForeignKeyConstraint(["unit_id"], ["syllabus_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.create_index("ix_videos_unit_version", ["unit_id", "notes_version"], unique=False)


def downgrade():
    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.drop_index("ix_videos_unit_version")

    op.drop_table("videos")
    with op.batch_alter_table("unit_progress", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_unit_progress_unit_id"))

    op.drop_table("unit_progress")
    with op.batch_alter_table("study_aids", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_study_aids_workspace_id"))

    op.drop_table("study_aids")
    with op.batch_alter_table("quizzes", schema=None) as batch_op:
        batch_op.drop_index("ix_quizzes_course_student")

    op.drop_table("quizzes")
    with op.batch_alter_table("chat_messages", schema=None) as batch_op:
        batch_op.drop_index("ix_chat_course_student")

    op.drop_table("chat_messages")
