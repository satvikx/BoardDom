from alembic import context
from app.core.config import Settings
from app.db.session import Base, build_engine
from app.models import entities  # noqa: F401

config = context.config
url = config.attributes.get("database_url") or Settings().resolved_database_url

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = build_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=Base.metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
