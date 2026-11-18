"""本地 Pilot 运维脚本使用的短时所有者身份。"""

from __future__ import annotations

import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from sqlalchemy import select


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def require_loopback_api_base(api_base: str) -> None:
    """阻止本地所有者令牌被发送到非回环地址。"""

    parsed = urlsplit(str(api_base or ""))
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in LOOPBACK_HOSTS:
        raise ValueError("本地 Pilot 运维只允许访问 loopback API")


async def load_unique_superadmin() -> tuple[int, str]:
    """读取唯一有效超级管理员，作为本地运维审计身份。"""

    from platform_core.storage.postgres.manager import pg_manager
    from platform_core.storage.postgres.models_business import User

    pg_manager.initialize()
    async with pg_manager.get_async_session_context() as session:
        result = await session.execute(
            select(User.id, User.uid).where(User.role == "superadmin", User.is_deleted == 0).order_by(User.id)
        )
        rows = list(result.all())
    if len(rows) != 1:
        raise RuntimeError(f"需要且仅允许一个有效超级管理员，当前为 {len(rows)} 个")
    return int(rows[0].id), str(rows[0].uid)


async def local_operator_headers(
    api_base: str,
    *,
    expires_minutes: int = 20,
) -> tuple[dict[str, str], str]:
    """生成仅供回环 Pilot 使用的短时 API Key 和审计 UID。"""

    from platform_core.repositories.api_key_repository import APIKeyRepository
    from platform_core.storage.postgres.manager import pg_manager
    from platform_core.storage.postgres.models_business import User
    from platform_core.utils.auth_utils import AuthUtils
    from platform_core.utils.datetime_utils import utc_now_naive

    require_loopback_api_base(api_base)
    if isinstance(expires_minutes, bool) or not 1 <= int(expires_minutes) <= 180:
        raise ValueError("本地 Pilot 运维令牌有效期必须在 1 到 180 分钟之间")
    superadmin_id, superadmin_uid = await load_unique_superadmin()
    full_key, key_hash, key_prefix = AuthUtils.generate_api_key()
    request_id = f"local-pilot-{secrets.token_hex(16)}"
    expires_at = utc_now_naive() + timedelta(minutes=int(expires_minutes))

    pg_manager.initialize()
    async with pg_manager.get_async_session_context() as session:
        user = await session.get(User, superadmin_id)
        if user is None or user.is_deleted:
            raise RuntimeError("本地 Pilot 超级管理员不存在或已注销")
        await APIKeyRepository(session).create(
            key_hash=key_hash,
            key_prefix=key_prefix,
            request_id=request_id,
            name="local-pilot-ephemeral",
            user_id=superadmin_id,
            department_id=user.department_id,
            expires_at=expires_at,
            created_by=superadmin_uid,
        )
        await session.commit()

    return {"Authorization": f"Bearer {full_key}"}, superadmin_uid
