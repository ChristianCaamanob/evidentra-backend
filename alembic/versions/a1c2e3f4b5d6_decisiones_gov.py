"""gobernanza: decisiones trazables + planes de mejora (memoria institucional)

Revision ID: a1c2e3f4b5d6
Revises: f7b2c9d1e3a4
Create Date: 2026-08-08

Idempotente: crea la tabla solo si no existe (en BD nueva la crea create_all).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "a1c2e3f4b5d6"
down_revision = "f7b2c9d1e3a4"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "decisiones_gov" not in insp.get_table_names():
        op.create_table(
            "decisiones_gov",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("autor_id", UUID(as_uuid=True), sa.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("ambito", sa.String(length=160), server_default="", index=True),
            sa.Column("nivel", sa.String(length=20), server_default="departamento"),
            sa.Column("tipo", sa.String(length=20), server_default="decision"),
            sa.Column("titulo", sa.String(length=300), server_default=""),
            sa.Column("problema", sa.Text(), server_default=""),
            sa.Column("evidencia", sa.Text(), server_default=""),
            sa.Column("alternativas", sa.Text(), server_default=""),
            sa.Column("decision", sa.Text(), server_default=""),
            sa.Column("responsable", sa.String(length=200), server_default=""),
            sa.Column("plazo", sa.String(length=40), server_default=""),
            sa.Column("indicador", sa.Text(), server_default=""),
            sa.Column("estado", sa.String(length=20), server_default="abierta"),
            sa.Column("resultado", sa.Text(), server_default=""),
            sa.Column("revision", sa.String(length=20), server_default=""),
            sa.Column("bitacora", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "decisiones_gov" in insp.get_table_names():
        op.drop_table("decisiones_gov")
