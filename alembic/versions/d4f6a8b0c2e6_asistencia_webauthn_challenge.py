"""asistencia: challenge WebAuthn transitorio en la matrícula

Revision ID: d4f6a8b0c2e6
Revises: c3e5f7a9d2b4
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa

revision = "d4f6a8b0c2e6"
down_revision = "c3e5f7a9d2b4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("asistencia_matriculas", sa.Column("webauthn_challenge", sa.String(length=255), nullable=True))
    op.add_column("asistencia_matriculas", sa.Column("webauthn_challenge_exp", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("asistencia_matriculas", "webauthn_challenge_exp")
    op.drop_column("asistencia_matriculas", "webauthn_challenge")
