from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from settings.db_config import get_database_url

_engine: Engine | None = None


class DatabaseNotConfiguredError(RuntimeError):
    """Banco ainda não foi configurado pela UI."""


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_database_url()
        if not url:
            raise DatabaseNotConfiguredError(
                "Banco de dados não configurado. Acesse Configurações e salve a conexão."
            )
        _engine = create_engine(url)
    return _engine


def configure_engine(url: str) -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url)


def test_connection(url: str | None = None) -> None:
    engine = create_engine(url) if url else get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        if url is not None:
            engine.dispose()


def get_session():
    with Session(get_engine()) as session:
        yield session
