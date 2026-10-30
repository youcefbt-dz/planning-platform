"""a department has a head

Revision ID: a7c3d19e5b20
Revises: 89461e85107f
"""
import sqlalchemy as sa
from alembic import op

revision = "a7c3d19e5b20"
down_revision = "89461e85107f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("org_unit", schema=None) as batch_op:
        batch_op.add_column(sa.Column("head_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_org_unit_head_id_user", "user", ["head_id"], ["id"])


def downgrade():
    with op.batch_alter_table("org_unit", schema=None) as batch_op:
        batch_op.drop_constraint("fk_org_unit_head_id_user", type_="foreignkey")
        batch_op.drop_column("head_id")
