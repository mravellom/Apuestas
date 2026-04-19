"""Test fixtures: in-memory SQLite database for fast tests."""

import asyncio
import os
import uuid

# Disable rate limiting in tests
os.environ["APP_ENV"] = "testing"

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models.user import User, UserConfig
from app.services.auth_service import create_access_token, hash_password

# Use aiosqlite for in-memory testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture
async def client(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user and return it."""
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        username="testuser",
        hashed_password=hash_password("testpass123"),
        role="free",
    )
    db_session.add(user)
    config = UserConfig(user_id=user.id)
    db_session.add(config)
    await db_session.commit()
    return user


@pytest.fixture
async def premium_user(db_session: AsyncSession) -> User:
    """Create a premium test user."""
    user = User(
        id=uuid.uuid4(),
        email="premium@example.com",
        username="premiumuser",
        hashed_password=hash_password("testpass123"),
        role="premium",
    )
    db_session.add(user)
    config = UserConfig(user_id=user.id)
    db_session.add(config)
    await db_session.commit()
    return user


@pytest.fixture
def auth_headers(test_user: User) -> dict:
    """Auth headers for the test user."""
    token = create_access_token(str(test_user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def premium_headers(premium_user: User) -> dict:
    """Auth headers for the premium user."""
    token = create_access_token(str(premium_user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Create an admin test user."""
    user = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        username="adminuser",
        hashed_password=hash_password("testpass123"),
        role="admin",
    )
    db_session.add(user)
    config = UserConfig(user_id=user.id)
    db_session.add(config)
    await db_session.commit()
    return user


@pytest.fixture
def admin_headers(admin_user: User) -> dict:
    token = create_access_token(str(admin_user.id))
    return {"Authorization": f"Bearer {token}"}
