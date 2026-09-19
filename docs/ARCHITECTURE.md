# 项目模块边界

本项目按“业务规则稳定、执行适配可替换、入口负责组装”的方向组织。模块之间通过小型契约和端口通信，避免业务模块直接依赖具体数据库、Provider 或 HTTP 框架。

```text
interfaces / api                 用户入口与协议适配
        |\
application --------------------- 用例编排与运行生命周期
        |  \
config   domain   contracts       不含业务实现的稳定值对象与共享契约
        |      |
persistence  providers  harness/tools  orchestration
        |
       SQL / 文件 / 外部服务适配
```

## 目录职责

- `domain`：研究问题、Packet、证据、报告和安全工作区等业务对象；不能导入入口、运行时或基础设施实现。
- `contracts`：Provider、工具、Agent 配置共享的稳定类型和名称目录；不包含网络、数据库或编排逻辑。
- `contracts.agents`：只描述 Agent 元数据和目录能力的 Protocol；具体 Registry 可以替换，工具与策略模块无需加载 Prompt/Provider 实现。
- `contracts.runtime`：Winning 工作流需要的最小运行时 Protocol（模型调用、蜂群、卡片和预算）；执行实现只依赖这些端口。
- `config`：进程边界配置和项目路径；只解析显式环境映射，不导入任何业务、框架或基础设施模块。入口通过 `load_settings()` 注入配置。
- `domain.conversation`、`domain.capability_portrait`：分支会话规则和能力画像格式化等纯业务规则；历史路径只保留兼容 re-export。
- `domain.swarm_strategy`：Query 派生的覆盖、招募决策、首波构成和运行状态；`SwarmState` 是领域对象，Agent 工作流旧路径仅保留兼容 re-export。
- `application`：创建、启动、恢复、归档研究任务等用例；通过 `application.ports` 依赖 Repository/Queue 协议。
- `orchestration`：研究路线、波次、制胜机理和交付策略；不负责 HTTP、CLI 或数据库连接。
- `harness`：Agent 会话、预算、上下文、检查点和恢复运行时。
- `providers`：模型后端适配；只消费 `contracts` 与 Provider 自身协议，不反向依赖工具执行器。
- `tools`：工具定义、权限、证据材料化和工具执行器。
- `persistence`：SQL/文件存储适配，实现应用端口和持久化接口。
- `api`、`interfaces`：组合根，负责把配置、端口和实现组装起来。

API 请求模型集中在 `api/schemas.py`；`api/app.py` 只负责组合路由、依赖和运行时服务，并通过兼容导出保持历史导入路径可用。应用工厂接受 `Settings` 注入，因此 API、Worker 和测试可以共享同一套配置解析。Winning 工作流的无副作用上下文投影集中在 `agents/workflows/shared_context.py`，错误类型集中在 `agents/workflows/errors.py`，各执行模式不再互相复制或反向导入实现细节。

## 开发约定

1. 新增跨模块数据结构先放入 `domain` 或 `contracts`，不要放进 Provider、API 或某个 Agent 实现文件。
2. 新增基础设施能力先定义端口（`Protocol`），再在 `persistence`、`providers` 或 `interfaces` 中实现。
3. 旧导入路径只保留兼容 re-export；新代码使用 canonical 路径，例如 `contracts.tools` 和 `contracts.catalog`。
4. 不在 `domain` 内部导入 `deep_runtime`。可选运行时通过注册式 adapter 接入，避免低层模块被运行时实现反向绑死。
5. 工具授权、路由、规划和覆盖只依赖 `contracts.agents.AgentSpec`；具体 `AgentRegistry` 只在 Agent 组合层和运行时组装处出现。
6. 提交前运行：

   ```bash
   PYTHONPATH=src python -m equipment_deep_research.architecture
   pytest tests/equipment_deep_research/unit/test_architecture_boundaries.py -q
   ```

   或运行统一入口：

   ```bash
   make check
   ```

架构检查使用 AST，不会执行应用代码；因此即使某个入口需要较重依赖，也能在干净环境中检查越层引用。默认还会检查模块的导入时强连通分量；如果需要审计函数内部的延迟适配器，可使用 `find_import_cycles(..., include_nested=True)` 查看延迟依赖环。

`module_metrics()` 和 `oversized_modules()` 提供静态重构雷达，不把历史大文件直接变成阻断性门禁。当前优先拆分顺序是：`api/app.py` 的路由与展示投影、`orchestration/runner.py` 的流水线阶段、`persistence/repositories.py` 的聚合仓储。拆分时保留旧导入路径的兼容 re-export，并为每个新边界增加单元测试，避免多人并行开发时发生隐式 API 破坏。
