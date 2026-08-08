"""RBAC por ámbito: membresias + registro de acceso a dato personal

Revision ID: b2d4f6a8c0e2
Revises: a1c2e3f4b5d6
Create Date: 2026-08-08

Idempotente: crea cada tabla solo si no existe (en BD nueva las crea create_all).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "b2d4f6a8c0e2"
down_revision = "a1c2e3f4b5d6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tablas = insp.get_table_names()
    if "membresias" not in tablas:
        op.create_table(
            "membresias",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("teacher_id", UUID(as_uuid=True), sa.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("nivel", sa.String(length=20), nullable=False),
            sa.Column("ambito", sa.String(length=160), server_default=""),
            sa.Column("acciones", sa.String(length=120), server_default="observar"),
            sa.Column("detalle", sa.String(length=20), server_default="agregado"),
            sa.Column("finalidad", sa.String(length=300), server_default=""),
            sa.Column("vigente_hasta", sa.DateTime(timezone=True), nullable=True),
            sa.Column("otorgada_por", UUID(as_uuid=True), nullable=True),
            sa.Column("activa", sa.Boolean(), server_default="true"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if "acceso_personal_log" not in tablas:
        op.create_table(
            "acceso_personal_log",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("teacher_id", UUID(as_uuid=True), sa.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("ambito", sa.String(length=160), server_default=""),
            sa.Column("sujeto_ref", sa.String(length=160), server_default=""),
            sa.Column("finalidad", sa.String(length=300), server_default=""),
            sa.Column("justificacion", sa.Text(), server_default=""),
            sa.Column("emergencia", sa.Boolean(), server_default="false"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tablas = insp.get_table_names()
    if "acceso_personal_log" in tablas:
        op.drop_table("acceso_personal_log")
    if "membresias" in tablas:
        op.drop_table("membresias")
