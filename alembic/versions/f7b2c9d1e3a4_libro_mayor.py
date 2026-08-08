"""libro mayor de la evidencia: registro append-only con hash encadenado + procedencia

Revision ID: f7b2c9d1e3a4
Revises: e5a1b2c3d4e5
Create Date: 2026-08-08

Idempotente: crea la tabla solo si no existe (en BD nueva la crea create_all con estas columnas;
en Render existente, esta migración la añade). Tabla APPEND-ONLY: no se altera ni se borra.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "f7b2c9d1e3a4"
down_revision = "e5a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "libro_mayor" not in insp.get_table_names():
        op.create_table(
            "libro_mayor",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("proyecto_id", UUID(as_uuid=True),
                      sa.ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("clave", sa.String(length=40), nullable=False, index=True),
            sa.Column("hash", sa.String(length=64), nullable=False),
            sa.Column("hash_prev", sa.String(length=64), nullable=True),
            sa.Column("n", sa.Integer(), nullable=True),
            sa.Column("plano", sa.String(length=20), nullable=False, server_default="método"),
            sa.Column("actor_id", UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "libro_mayor" in insp.get_table_names():
        op.drop_table("libro_mayor")
