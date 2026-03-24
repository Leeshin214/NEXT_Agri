from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# get_database_url()로 실제 사용할 URL 결정
# (DATABASE_URL 직접 설정 또는 SUPABASE_DB_* 개별 필드 조합)
_database_url = settings.get_database_url()

engine = create_async_engine(
    _database_url,
    echo=False,
    # Supabase connection pooler(Transaction mode) 사용 시
    # prepared statement를 비활성화해야 함 (pooler가 statement를 공유하지 못함)
    connect_args={"statement_cache_size": 0} if "pooler.supabase.com" in _database_url else {},
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
