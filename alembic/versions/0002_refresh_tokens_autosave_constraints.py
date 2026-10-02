"""refresh_tokens table, test_attempts.saved_answers, attempt unique constraint + indexes

Safe to run on:
  * an old database (adds what is missing), and
  * a database created by the current code (every step checks first and skips
    what already exists).

Revision ID: 0002_refresh_autosave
Revises: 0001_baseline
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_refresh_autosave"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _insp():
    # Fresh inspector each time: SQLAlchemy caches results per inspector.
    return sa.inspect(op.get_bind())


def _has_index(table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in _insp().get_indexes(table))


def _ensure_index(table: str, name: str, columns: list[str]) -> None:
    if _insp().has_table(table) and not _has_index(table, name):
        op.create_index(name, table, columns)


def upgrade() -> None:
    insp = _insp()

    # 1. Refresh tokens (cookie login) -------------------------------------
    if not insp.has_table("refresh_tokens"):
        op.create_table(
            "refresh_tokens",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    _ensure_index("refresh_tokens", "ix_refresh_tokens_user_id", ["user_id"])
    if _insp().has_table("refresh_tokens") and not _has_index("refresh_tokens", "ix_refresh_tokens_token_hash"):
        op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)
    _ensure_index("refresh_tokens", "ix_refresh_tokens_expires_at", ["expires_at"])

    # 2. Autosaved answers column -------------------------------------------
    cols = {c["name"] for c in _insp().get_columns("test_attempts")}
    if "saved_answers" not in cols:
        op.add_column("test_attempts", sa.Column("saved_answers", sa.Text(), nullable=True))

    # 3. One attempt per student per test (enforced by the database) ---------
    insp = _insp()
    has_unique = any(
        uc["name"] == "uq_attempt_test_student" for uc in insp.get_unique_constraints("test_attempts")
    ) or any(
        ix["name"] == "uq_attempt_test_student" for ix in insp.get_indexes("test_attempts")
    )
    if not has_unique:
        duplicates = op.get_bind().execute(sa.text(
            "SELECT test_id, student_id, COUNT(*) AS n FROM test_attempts "
            "GROUP BY test_id, student_id HAVING COUNT(*) > 1"
        )).fetchall()
        if duplicates:
            raise RuntimeError(
                f"{len(duplicates)} student(s) already have more than one attempt for the same test. "
                "Delete or merge the extra rows in test_attempts, then run this migration again."
            )
        with op.batch_alter_table("test_attempts") as batch:
            batch.create_unique_constraint("uq_attempt_test_student", ["test_id", "student_id"])

    # 4. Indexes used by the test-taking queries ---------------------------
    _ensure_index("test_attempts", "ix_test_attempts_test_id", ["test_id"])
    _ensure_index("test_attempts", "ix_test_attempts_student_id", ["student_id"])
    _ensure_index("test_answers", "ix_test_answers_attempt_id", ["attempt_id"])
    _ensure_index("enrollments", "ix_enrollments_student_id", ["student_id"])
    _ensure_index("enrollments", "ix_enrollments_course_id", ["course_id"])


def downgrade() -> None:
    # Only the clearly-safe parts. The unique constraint and indexes are left
    # in place: removing them would not help and could slow the test down.
    with op.batch_alter_table("test_attempts") as batch:
        batch.drop_column("saved_answers")
    op.drop_table("refresh_tokens")
