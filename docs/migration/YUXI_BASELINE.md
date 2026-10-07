# 第三方来源记录（Yuxi）

本文只记录历史并入与许可证线索，不是产品对外说明。当前产品身份是「装备智能研究平台」，内核模块名为 `platform_core`。

Yuxi v0.7.3（提交 `9b67368c6baeb731f89e1076da8a1b68ff52178a`，MIT）的代码已吸收进本仓库：原 `backend/package/yuxi` 重命名为 `backend/package/platform_core`，Python 发行名 `platform-core`。运行时不依赖 `reference/Yuxi-main`，也不以 Yuxi 作为产品名。

## 边界

- HTTP 只在 `backend/server`；平台用例在 `platform_core.services`。
- `equipment_deep_research` 不得反向依赖 `platform_core`、PostgreSQL 驱动或 Vue。
- 装备研究 Durable Task 类型为 `equipment_research`，独立并发配额。
- 产品展示名统一为「装备智能研究平台」，主色 `#625ff0`。
- 当前运行契约统一使用 `DEEP_RESEARCH_*`；启动脚本会原值迁移历史 `.env` 键，后端在过渡期仅保留旧键的只读回退。
- 模型设置是独立导航页 `/models`，管理员在此维护 Model Provider；装备研究任务通过 `model_spec`（`provider_id:model_id`）引用同一套凭证，不再使用第二套密钥库。
