from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from backend.db.models import Base
import os

DB_PATH = os.environ.get("SQL_TO_DYNAMODB_DESIGN_MENTOR_DB", "app.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
