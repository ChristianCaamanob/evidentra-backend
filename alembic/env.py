"""Alembic environment de Evidentra/Evalys.

Fuente de verdad del esquema: los modelos SQLAlchemy (Base.metadata). La URL sale de la
misma config de la app (settings.database_url), así Alembic y la app apuntan a la MISMA BD.
"""
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# --- raíz del proyecto en el path (para importar 'app') ---
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.models.base import Base  # noqa: E402

# Importar TODOS los módulos de modelos para poblar Base.metadata (autogenerate los verá).
import app.models.teacher  # noqa: E402,F401
import app.models.course  # noqa: E402,F401
import app.models.student  # noqa: E402,F401
import app.models.assessment  # noqa: E402,F401
import app.models.answer_key  # noqa: E402,F401
import app.models.scan  # noqa: E402,F401
import app.models.result  # noqa: E402,F401
import app.models.feedback  # noqa: E402,F401
import app.models.curriculo  # noqa: E402,F401
import app.models.validacion  # noqa: E402,F401
import app.models.grupo  # noqa: E402,F401
import app.models.en_vivo  # noqa: E402,F401
import app.models.aprendizaje  # noqa: E402,F401
import app.models.password_reset  # noqa: E402,F401
import app.models.suscripcion  # noqa: E402,F401

config = context.config

# URL desde la app (normaliza postgres:// -> postgresql://).
_url = settings.database_url
if _url.startswith("postgres://"):
    _url = _url.replace("postgres://", "postgresql://", 1)
config.set_main_option("sqlalchemy.url", _url)

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        pass

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=_url, target_metadata=target_metadata,
                      literal_binds=True, compare_type=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
