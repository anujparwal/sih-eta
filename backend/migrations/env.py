from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.database import database_url
from app.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)


def include_object(obj, name, type_, reflected, compare_to):
    # PostGIS owns spatial_ref_sys; application migrations must never drop it.
    return not (type_ == "table" and name not in Base.metadata.tables)


url = config.attributes.get("database_url", database_url())
if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=Base.metadata, include_object=include_object
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
