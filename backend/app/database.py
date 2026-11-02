from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

from .config import DATABASE_URL

TRANSACTION_POOLER_PORT = 6543


def engine_options(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    if make_url(url).port == TRANSACTION_POOLER_PORT:
        # Pooler Supabase en mode transaction : il gère le pool, et la connexion serveur peut changer
        # entre deux transactions, donc pas de requêtes préparées.
        return {"poolclass": NullPool, "connect_args": {"prepare_threshold": None}}
    # Petit pool : chaque instance serverless ouvre ses propres connexions et le serveur en limite le nombre.
    return {"pool_size": 2, "max_overflow": 3, "pool_pre_ping": True, "pool_recycle": 300}


engine = create_engine(DATABASE_URL, **engine_options(DATABASE_URL))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
