"""modo en vivo: banco de ítems + config de sesión + layout por participante

Revision ID: b2d4f6a8c1e2
Revises: a1c2e3f4b5d6
Create Date: 2026-07-17

Aditiva y no destructiva: columnas nuevas nullables o con server_default, para no
tocar filas existentes. Habilita la retroalimentación al alumno, el ritmo self-paced,
el barajado por participante y el contenido de ítems (enunciado/opciones/justificación).
"""
from alembic import op
import sqlalchemy as sa

revision = "b2d4f6a8c1e2"
down_revision = "a1c2e3f4b5d6"
branch_labels = None
depends_on = None


def upgrade():
    # ── config de la sesión (la fija el docente antes de abrir la sala) ──
    op.add_column("sesiones_en_vivo",
                  sa.Column("retro_alumno", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("sesiones_en_vivo",
                  sa.Column("revelar_correccion", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("sesiones_en_vivo",
                  sa.Column("modo_ritmo", sa.String(length=20), nullable=False, server_default="docente"))
    op.add_column("sesiones_en_vivo",
                  sa.Column("shuffle_preguntas", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("sesiones_en_vivo",
                  sa.Column("shuffle_opciones", sa.Boolean(), nullable=False, server_default="false"))

    # ── distribución personal del quiz por participante (barajado + progreso self-paced) ──
    op.add_column("participantes_vivo", sa.Column("layout_json", sa.JSON(), nullable=True))
    op.add_column("participantes_vivo",
                  sa.Column("progreso", sa.Integer(), nullable=False, server_default="0"))

    # ── banco de ítems: contenido para mostrar la pregunta y justificar (opcional) ──
    op.add_column("answer_key_items", sa.Column("opciones_json", sa.JSON(), nullable=True))
    op.add_column("answer_key_items", sa.Column("justificacion", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("answer_key_items", "justificacion")
    op.drop_column("answer_key_items", "opciones_json")
    op.drop_column("participantes_vivo", "progreso")
    op.drop_column("participantes_vivo", "layout_json")
    op.drop_column("sesiones_en_vivo", "shuffle_opciones")
    op.drop_column("sesiones_en_vivo", "shuffle_preguntas")
    op.drop_column("sesiones_en_vivo", "modo_ritmo")
    op.drop_column("sesiones_en_vivo", "revelar_correccion")
    op.drop_column("sesiones_en_vivo", "retro_alumno")
