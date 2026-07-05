import uuid
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin, UUIDMixin

# Roles de acceso. Jerarquia de alcance:
#   profesor     -> modulo profesor + estudiante (sobre lo suyo)
#   investigador -> estudiante + profesor + investigador (superconjunto del profesor)
#   director     -> SOLO ver/exportar datos de estudiantes y de todos los profesores; no modifica
#   creador      -> todo, incluido cambios estructurales/licencias (superadmin)
ROL_PROFESOR = "profesor"
ROL_INVESTIGADOR = "investigador"
ROL_DIRECTOR = "director"
ROL_CREADOR = "creador"
ROLES = (ROL_PROFESOR, ROL_INVESTIGADOR, ROL_DIRECTOR, ROL_CREADOR)


class Teacher(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "teachers"
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    institution: Mapped[str] = mapped_column(String(255), default="Universidad San Sebastián")
    # Aditivo: las filas existentes quedan como 'profesor' (server_default), sin romper el MVP.
    rol: Mapped[str] = mapped_column(String(20), default=ROL_PROFESOR,
                                     server_default=ROL_PROFESOR, nullable=False)
