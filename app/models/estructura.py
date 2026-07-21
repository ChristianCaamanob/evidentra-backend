from sqlalchemy import String, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class EstructuraInstitucional(UUIDMixin, TimestampMixin, Base):
    """Config 'Lego' de la estructura institucional: Facultades, Departamentos y Profesores son
    BLOQUES que el director/admin crea (nombre + código), y los cursos REALES se ensamblan
    asignándolos a un departamento y a profesores. Un único registro por institución
    (scope='global'). No altera notas (G1); solo organiza y alimenta el agregado del Director.

    payload = {
      "facultades":   [{"id","nombre","codigo"}],
      "departamentos":[{"id","nombre","codigo","facultad_id"}],
      "profesores":   [{"id","nombre","codigo"}],
      "cursos": { "<course_id>": {"departamento_id","profesores":["<prof_id>", ...]} }
    }
    """
    __tablename__ = "estructura_institucional"

    scope: Mapped[str] = mapped_column(String(80), unique=True, default="global")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
