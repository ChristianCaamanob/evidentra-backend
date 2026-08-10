"""guarida de runi: pausas restaurativas (tiempo validado por servidor)

Revision ID: d5f7a9c1e3b7
Revises: c4e6f8b0d2a6
Create Date: 2026-08-09

Idempotente: crea la tabla solo si no existe (en BD nueva la crea create_all).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "d5f7a9c1e3b7"
down_revision = "c4e6f8b0d2a6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "runi_breaks" not in insp.get_table_names():
        op.create_table(
            "runi_breaks",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("pseudo_id", sa.String(length=80), index=True, nullable=False),
            sa.Column("course_id", sa.String(length=64), index=True, nullable=True),
            sa.Column("source_session_id", sa.String(length=80), nullable=True),
            sa.Column("zone", sa.String(length=20), server_default="calm"),
            sa.Column("planned_minutes", sa.Integer(), server_default="5"),
            sa.Column("extended_count", sa.Integer(), server_default="0"),
            sa.Column("added_minutes_total", sa.Integer(), server_default="0"),
            sa.Column("actual_seconds", sa.Integer(), nullable=True),
            sa.Column("estado", sa.String(length=16), server_default="active", index=True),
            sa.Column("outcome_source", sa.String(length=40), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "runi_breaks" in insp.get_table_names():
        op.drop_table("runi_breaks")
