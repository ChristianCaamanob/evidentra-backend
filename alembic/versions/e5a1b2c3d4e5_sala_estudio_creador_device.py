"""sala de estudio: creador_device para owner-check al cerrar

Revision ID: e5a1b2c3d4e5
Revises: d4f6a8b0c2e6
Create Date: 2026-08-08

Defensiva/idempotente: solo agrega la columna si la tabla existe y la columna falta
(en BD nueva la tabla la crea create_all con la columna ya incluida; en Render existente,
esta migración añade la columna sin romper nada).
"""
from alembic import op
import sqlalchemy as sa

revision = "e5a1b2c3d4e5"
down_revision = "d4f6a8b0c2e6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "salas_estudio" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("salas_estudio")]
        if "creador_device" not in cols:
            op.add_column("salas_estudio", sa.Column("creador_device", sa.String(length=64), nullable=True))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "salas_estudio" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("salas_estudio")]
        if "creador_device" in cols:
            op.drop_column("salas_estudio", "creador_device")
