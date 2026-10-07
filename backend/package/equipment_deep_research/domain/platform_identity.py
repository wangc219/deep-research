"""平台验证后注入的请求身份；领域代码不依赖 HTTP 或平台数据库。"""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformIdentity:
    """由平台用户记录确定的个人数据边界。"""

    uid: str
    tenant_id: str
    superadmin: bool = False

    def owns_run(self, run: object) -> bool:
        """判断任务是否可读；历史无归属任务仅允许超级管理员查看。"""

        return self.superadmin or self.can_mutate_run(run)

    def can_mutate_run(self, run: object) -> bool:
        """个人任务允许真实所有者或超级管理员修改。"""

        return self.superadmin or (
            getattr(run, "workspace_id", "") == self.uid
            and getattr(run, "tenant_id", "") == self.tenant_id
        )

    def can_mutate_owner(self, owner_uid: object) -> bool:
        """个人记录允许真实所有者或超级管理员修改。"""

        return self.superadmin or (bool(self.uid) and str(owner_uid or "") == self.uid)


platform_identity: ContextVar[PlatformIdentity | None] = ContextVar("platform_identity", default=None)
