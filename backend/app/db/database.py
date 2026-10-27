from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

# Managed Postgres (Neon) closes idle connections and suspends the database
# when idle. pool_pre_ping checks a pooled connection before reusing it, and
# pool_recycle retires connections before the server would drop them, so a
# request never fails with "connection is closed".
engine = create_async_engine(
    settings.database_url,
    echo=settings.sql_echo,
    pool_pre_ping=True,
    pool_recycle=300,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
