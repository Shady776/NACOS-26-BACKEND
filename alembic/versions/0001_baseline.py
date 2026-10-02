"""baseline: the schema as created by Base.metadata.create_all before Alembic

Nothing to do. This revision only marks "the database as it was before we
started using migrations", so existing databases and brand-new ones both end up
at the same starting point.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-01
"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
