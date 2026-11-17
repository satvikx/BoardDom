from collections.abc import Generator
from pathlib import Path

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str):
    url = make_url(database_url)
    sqlite = url.get_backend_name() == "sqlite"
    if sqlite and url.database not in {None, "", ":memory:"}:
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        database_url, connect_args={"check_same_thread": False, "timeout": 20} if sqlite else {}
    )
    if sqlite:

        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db(request: Request) -> Generator[Session]:
    with request.app.state.session_factory() as session:
        yield session
