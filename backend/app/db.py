"""The database engine. Every engine the platform makes goes through make_engine: its URL carries no credentials
(PGUSER and PGPASSWORD supply them, app.config), its schema is the connection's search_path, and a database error
never shows the username or the password."""
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


def scrub(text: str) -> str:
    """`text` with the configured username and password replaced by ***."""
    for secret in sorted(settings.secrets(), key=len, reverse=True):
        text = text.replace(secret, "***")
    return text


def make_engine(url: str, **kwargs) -> Engine:
    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "handle_error")
    def _no_credentials(context) -> None:
        # The driver's exception and SQLAlchemy's wrapper of it are rewritten in place, so neither the message nor
        # any traceback of them, chained or not, carries a credential.
        for exc in (context.original_exception, context.sqlalchemy_exception):
            if exc is not None and exc.args:
                exc.args = tuple(scrub(a) if isinstance(a, str) else a for a in exc.args)
        if context.sqlalchemy_exception is not None and hasattr(context.sqlalchemy_exception, "orig"):
            context.sqlalchemy_exception.orig = context.original_exception

    return engine


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
