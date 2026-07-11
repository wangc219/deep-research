# Phase 1 Task 1 Report

## RED

- 新建 `tests/equipment_deep_research/unit/test_runtime_types.py` 后运行：
  `python3 -m pytest tests/equipment_deep_research/unit/test_runtime_types.py -q`
- 结果：按预期在收集阶段失败，`ModuleNotFoundError: No module named
  'equipment_deep_research.domain.proposals'`。
- 失败原因是本任务运行时类型尚未实现，不是测试拼写或环境错误。

## GREEN

- 聚焦测试：`7 passed in 0.01s`。
- `equipment_deep_research` 相关单元测试：`55 passed in 0.15s`。
- 仓库全量测试：`98 passed in 0.42s`。
- JSON smoke：所有新增类型的 `to_plain()` 输出均可 `json.dumps()`；
  `ToolDefinition.handler` 不进入 plain data。
- 直接 Python smoke 首次未设置 `PYTHONPATH=src`，因此无法导入本地包；按项目
  `pyproject.toml` 的 src 布局补上该环境后重跑通过。

## Interfaces

- `domain.proposals`
  - `DomainWriteProposal(proposal_id, object_type, operation, payload,
    idempotency_key)`
  - `TraceProposal(proposal_id, event_type, actor, payload)`
- `tools.definitions`
  - `ToolCall(call_id, name, arguments)`
  - `ToolExecutionContext(run_id, agent_id, permissions)`
  - `ToolResult(call_id, content, details, domain_proposals, trace_proposals,
    is_error)`
  - `ToolDefinition(name, description, input_schema, handler)`；handler 必须是
    async callable。
- `harness.events`
  - `RuntimeEvent(category, event_type, run_id, payload, sequence, event_id,
    created_at, schema_version)`
- `harness.event_bus`
  - `EventBus.subscribe()` 返回 unsubscribe callable。
  - `EventBus.publish()` 在分发前按 `run_id` 分配单调递增 sequence，返回净化后
    的不可变事件。
  - subscriber 异常被隔离并计入 `listener_error_count`；已分配 sequence 不回收，
    其他 subscriber 继续收到同一事件。

## Security And Serialization

- payload 脱敏递归处理 dict/list/tuple。
- key 归一化后识别 `authorization`、`api_key`、`token`、`password`、
  `secret` 及其常见前缀形式（例如 `refresh_token`、`client_secret`）。
- 长字符串只保留指定长度的前缀并追加 `<truncated>`，不保留尾部。
- RuntimeEvent 自动生成稳定 `event_id`、UTC ISO `created_at` 和
  `schema_version="1.0"`。
- 所有新增值类型提供 `to_plain()`；ToolDefinition 明确排除 handler。

## Dependency Scan

- 命令：
  `rg -n "equipment_deep_research\.orchestration" src/equipment_deep_research/harness src/equipment_deep_research/tools/definitions.py`
- 结果：无命中（`rg` exit 1 表示未找到匹配）。
- 新增依赖方向为 `tools -> domain`、`harness.events -> domain`、
  `harness.event_bus -> harness.events`，未导入 orchestration。

## Commit

- 原子提交主题：`feat: add runtime event and proposal kernel`
- 提交仅包含本任务 5 个实现/测试文件及本报告；最终提交哈希在任务最终回复中报告。

## Self Review

- 未修改或回退其他工作者文件。
- `ToolResult.domain_proposals` 与 `trace_proposals` 使用独立字段和独立
  default factory，无混流或共享列表。
- EventBus 在 subscriber 调用前完成 sequence 分配，并用锁保护每个 run 的计数
  与订阅列表快照。
- 原 RuntimeEvent 不被修改；publish 使用 `dataclasses.replace()` 产生安全事件，
  保留 event id 和创建时间。
- 范围保持在 brief 指定所有权内，未增加不必要的包导出或 orchestration 耦合。
