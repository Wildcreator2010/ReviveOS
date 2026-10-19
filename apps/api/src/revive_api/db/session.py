from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def session_factory(url: str):
    engine = create_async_engine(url)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
