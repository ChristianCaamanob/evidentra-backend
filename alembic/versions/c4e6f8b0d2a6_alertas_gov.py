"""gobernanza: alertas escalonadas (motor de escalamiento controlado)

Revision ID: c4e6f8b0d2a6
Revises: b2d4f6a8c0e2
Create Date: 2026-08-09

Idempotente: crea la tabla solo si no existe (en BD nueva la crea create_all).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "c4e6f8b0d2a6"
down_revision = "b2d4f6a8c0e2"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "alertas_gov" not in insp.get_table_names():
        op.create_table(
            "alertas_gov",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("autor_id", UUID(as_uuid=True), sa.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("ambito", sa.String(length=160), server_default="", index=True),
            sa.Column("nivel", sa.String(length=20), server_default="carrera"),
            sa.Column("titulo", sa.String(length=300), server_default=""),
            sa.Column("sujeto_ref", sa.String(length=200), server_default=""),
            sa.Column("origen", sa.String(length=40), server_default="manual"),
            sa.Column("fundamento", sa.Text(), server_default=""),
            sa.Column("certeza", sa.String(length=10), server_default="media"),
            sa.Column("nivel_alerta", sa.String(length=20), server_default="informativa"),
            sa.Column("estado", sa.String(length=20), server_default="abierta"),
            sa.Column("responsable", sa.String(length=200), server_default=""),
            sa.Column("decision_id", UUID(as_uuid=True), nullable=True),
            sa.Column("bitacora", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "alertas_gov" in insp.get_table_names():
        op.drop_table("alertas_gov")
