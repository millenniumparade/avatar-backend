"""数据库会话管理。"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db_session() -> Generator[Session, None, None]:
    """提供数据库会话依赖。

    输入:
        无，由 FastAPI Depends 调用。

    输出:
        Generator[Session, None, None]: 请求生命周期内可用的数据库会话。
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

