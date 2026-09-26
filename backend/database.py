from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# DATABASE_URL = "postgresql://postgres:postgres123@localhost:5432/phishing_simulation"
DATABASE_URL = "postgresql+psycopg2://postgres:postgres123@localhost:5432/phishing_simulation"

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()