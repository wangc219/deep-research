# Contributing

感谢参与装备能力 Deep Research 项目。代码按依赖方向组织：入口组装
`application`，业务对象位于 `domain`，稳定共享类型位于 `contracts`，外部系统
适配位于 `providers`、`persistence` 和 `tools`。运行时 Protocol 统一放在
`contracts.runtime`，蜂群策略和运行状态统一放在 `domain.swarm_strategy`。新增模块应依赖协议和数据对象，
不要在业务模块中直接读取环境变量、创建数据库连接或调用 Web 框架。

## 开发流程

1. 从 `main` 创建短生命周期分支，分支名使用 `feature/`、`fix/` 或 `refactor/` 前缀。
2. 每个提交只解决一个可审查的问题；提交信息使用动词开头，例如 `refactor: extract settings boundary`。
3. 运行 `make check`，再运行与改动相关的单元或集成测试。
4. Pull Request 说明行为变化、迁移影响、验证命令和已知限制。涉及配置时只提交 `.env.example` 或脱敏示例，禁止提交 API Key、数据库文件和运行产物。

## 模块边界

提交前的 AST 检查会阻止低层模块反向依赖 API、Worker、Provider 或数据库实现，
并检测导入环。若确实需要跨层通信，请先在 `application/ports.py` 或
`contracts/` 定义小型协议，再由组合根注入实现。

## 测试分层

- `tests/equipment_deep_research/unit`：纯函数、协议和边界规则，提交必须通过。
- `tests/equipment_deep_research/integration`：数据库、Provider 和 Worker 协作。
- `tests/equipment_deep_research/e2e`：完整运行链路，按变更范围选择执行。

默认 fake provider 用于离线验证；真实 Provider 测试必须显式配置凭据并在 PR 中说明。
