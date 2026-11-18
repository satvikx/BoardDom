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
    sqlite = engine.dialect.name == "sqlite"
    with engine.connect() as connection:
        if sqlite:
            # Batch mode rebuilds tables (copy, DROP, rename). With foreign keys on, the
            # DROP of a referenced table (e.g. users) cascades and deletes child rows.
            # The pragma only takes effect outside a transaction, so set it first.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        context.configure(
            connection=connection, target_metadata=Base.metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
            if sqlite:
                violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise RuntimeError(f"Migration left foreign key violations: {violations}")
        if sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    engine.dispose()
