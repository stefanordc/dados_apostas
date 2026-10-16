from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from .config import settings

app_engine: Engine = create_engine(
    settings.app_database_url,
    pool_pre_ping=True,
    pool_recycle=300,
)

history_engine: Engine = create_engine(
    settings.history_database_url,
    pool_pre_ping=True,
    pool_recycle=300,
)

def history_connection():
    conn = history_engine.connect()
    conn.exec_driver_sql("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    return conn
