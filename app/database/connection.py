import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from database.models import Base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./scrabble.db")

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def init_db() -> None:
    """Crea todas las tablas en la base de datos si aún no existen."""
    Base.metadata.create_all(bind=engine)


def get_session() -> Generator[Session, None, None]:
    """Generador de sesiones para uso seguro en bloques try/finally."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
