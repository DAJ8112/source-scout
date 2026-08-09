from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


def database_url() -> str:
    return settings.database_url


def make_engine(url: str | None = None):
    target = url or database_url()
    kwargs = {"check_same_thread": False} if target.startswith("sqlite") else {}
    return create_engine(target, connect_args=kwargs, pool_pre_ping=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_session() -> Generator[Session]:
    with SessionLocal() as session:
        yield session
