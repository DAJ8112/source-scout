from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


def database_url() -> str:
    target = settings.database_url
    if target.startswith("postgres://"):
        target = f"postgresql://{target.removeprefix('postgres://')}"
    url = make_url(target)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


def make_engine(url: str | None = None):
    target = url or database_url()
    kwargs = {"check_same_thread": False} if target.startswith("sqlite") else {}
    return create_engine(target, connect_args=kwargs, pool_pre_ping=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_session() -> Generator[Session]:
    with SessionLocal() as session:
        yield session
