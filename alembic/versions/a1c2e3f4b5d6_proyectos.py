"""proyectos: contenedor persistente del investigador

Revision ID: a1c2e3f4b5d6
Revises: 00bdf9aea347
Create Date: 2026-07-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "a1c2e3f4b5d6"
down_revision = "00bdf9aea347"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "proyectos",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("investigador_id", UUID(as_uuid=True),
                  sa.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("titulo", sa.String(length=300), nullable=False),
        sa.Column("pregunta", sa.String(length=1000), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="borrador"),
        sa.Column("datos", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # El índice ix_proyectos_investigador_id ya lo crea la columna con index=True arriba;
    # no lo dupliques aquí (create_index redundante rompía el upgrade: "already exists").


def downgrade():
    op.drop_table("proyectos")
