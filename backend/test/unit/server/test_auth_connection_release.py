"""认证结束应归还连接，避免并发请求等待嵌套业务查询时占满连接池。"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from platform_core.storage.postgres.models_business import APIKey, Base, Department, User
from platform_core.utils.auth_utils import AuthUtils
from server.utils.auth_middleware import get_current_user


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["jwt", "api_key"])
async def test_auth_returns_connection_before_repository_read(tmp_path, monkeypatch, kind):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-auth-pool-secret-at-least-32-characters")
    engine = create_async_engine(
        "sqlite+aiosqlite:///" + str(tmp_path / "auth.db"),
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as db:
            department = Department(name="Pool test")
            user = User(
                uid="auth-pool-user", username="Pool user", role="user", password_hash="unused", department=department
            )
            db.add(user)
            await db.flush()
            user_id = user.id
            if kind == "api_key":
                token, digest, prefix = AuthUtils.generate_api_key()
                db.add(
                    APIKey(
                        key_hash=digest,
                        key_prefix=prefix,
                        name="Pool test key",
                        user_id=user.id,
                        created_by=str(user.id),
                    )
                )
            else:
                token = AuthUtils.create_access_token({"sub": str(user.id)})
            await db.commit()
        async with factory() as authentication_db:
            user = await get_current_user("Bearer " + token, authentication_db)
            assert user.uid == "auth-pool-user" and user.role == "user"
            assert not authentication_db.in_transaction()
            assert engine.sync_engine.pool.checkedout() == 0
            # 认证 Session 尚未关闭，唯一的连接仍必须能被独立 repository 使用。
            async with factory() as repository_db:
                assert await repository_db.scalar(select(User.uid).where(User.id == user_id)) == "auth-pool-user"
                if kind == "api_key":
                    assert await repository_db.scalar(select(APIKey.last_used_at)) is not None
    finally:
        await engine.dispose()
