"""Database connections shared by migrations, seeding and request sessions."""

import os
from functools import lru_cache

from sqlalchemy import URL, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def database_url() -> URL:
    if configured := os.getenv("DATABASE_URL"):
        url = make_url(configured)
        if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise ValueError("DATABASE_URL must use PostgreSQL")
        return url.set(drivername="postgresql+psycopg")
    return URL.create(
        "postgresql+psycopg",
        username=os.getenv("POSTGRES_USER", "sih_eta"),
        password=os.getenv("POSTGRES_PASSWORD", "sih_eta_local"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "sih_eta"),
    )


@lru_cache
def get_engine():
    return create_engine(database_url(), pool_pre_ping=True, connect_args={"connect_timeout": 3})


def get_session():
    with Session(get_engine()) as session:
        yield session
