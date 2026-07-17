"""asistencia por curso: nómina + passkeys + sesiones + marcas

Revision ID: c3e5f7a9d2b4
Revises: b2d4f6a8c1e2
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "c3e5f7a9d2b4"
down_revision = "b2d4f6a8c1e2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "asistencia_matriculas",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey("courses.id"), nullable=False, index=True),
        sa.Column("student_id", sa.String(length=64), nullable=True),
        sa.Column("nombre", sa.String(length=160), nullable=False),
        sa.Column("correo", sa.String(length=160), nullable=False, index=True),
        sa.Column("identificador", sa.String(length=80), nullable=True),
        sa.Column("rut", sa.String(length=20), nullable=True),
        sa.Column("carrera", sa.String(length=160), nullable=True),
        sa.Column("seccion", sa.String(length=80), nullable=True),
        sa.Column("asignatura", sa.String(length=160), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="invitado"),
        sa.Column("invite_token", sa.String(length=48), nullable=True),
        sa.Column("validado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("course_id", "correo", name="uq_matricula_curso_correo"),
        sa.UniqueConstraint("invite_token", name="uq_matricula_invite_token"),
    )
    op.create_table(
        "asistencia_dispositivos",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("matricula_id", UUID(as_uuid=True), sa.ForeignKey("asistencia_matriculas.id"), nullable=False, index=True),
        sa.Column("credential_id", sa.String(length=500), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("sign_count", sa.Integer(), server_default="0"),
        sa.Column("aaguid", sa.String(length=64), nullable=True),
        sa.Column("transports", sa.JSON(), nullable=True),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("credential_id", name="uq_dispositivo_credential_id"),
    )
    op.create_table(
        "asistencia_sesiones",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey("courses.id"), nullable=False, index=True),
        sa.Column("abierta_por", sa.String(length=64), nullable=False),
        sa.Column("titulo", sa.String(length=200), server_default="Asistencia"),
        sa.Column("fecha", sa.String(length=10), nullable=False),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fin", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="abierta"),
        sa.Column("codigo", sa.String(length=12), nullable=False),
        sa.Column("secreto", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("codigo", name="uq_sesion_asistencia_codigo"),
    )
    op.create_table(
        "asistencia_marcas",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("sesion_id", UUID(as_uuid=True), sa.ForeignKey("asistencia_sesiones.id"), nullable=False, index=True),
        sa.Column("matricula_id", UUID(as_uuid=True), sa.ForeignKey("asistencia_matriculas.id"), nullable=False, index=True),
        sa.Column("metodo", sa.String(length=20), server_default="passkey"),
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="presente"),
        sa.Column("anomalias", sa.JSON(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("marcada_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("sesion_id", "matricula_id", name="uq_marca_sesion_matricula"),
    )


def downgrade():
    op.drop_table("asistencia_marcas")
    op.drop_table("asistencia_sesiones")
    op.drop_table("asistencia_dispositivos")
    op.drop_table("asistencia_matriculas")
