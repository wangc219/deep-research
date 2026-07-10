# Phase 0 Task 1 Report

## 状态

DONE

## 变更文件

- `src/equipment_deep_research/domain/messages.py`
- `src/equipment_deep_research/domain/planning.py`
- `src/equipment_deep_research/domain/models.py`
- `tests/equipment_deep_research/unit/test_domain_contracts.py`

## 实现说明

- 新增冻结领域消息 `TaskEnvelope`，实现目标路由、目标描述和返回契约校验。
- 新增冻结领域消息 `RecallEnvelope`，实现 agent 优先、capability 次之、不可路由兜底的 `target_key()`。
- 新增冻结计划对象 `ResearchPlanNode`，校验节点身份、状态、目标和自依赖。
- 新增冻结计划对象 `ResearchPlanGraph`，`ready_nodes()` 仅返回 `pending` 且全部依赖已 `completed` 的节点；缺失依赖不会被视为已完成。
- 所有本任务新增跨进程领域对象均包含稳定身份字段、`schema_version="1.0"` 和 UTC ISO `created_at`，并可通过项目标准 `to_plain()` 转换后由 `json.dumps()` 序列化。
- `ResearchPlanNode` 保持 brief 中六个位置参数的构造方式；`ResearchPlanGraph(nodes=...)` 保持直接构造兼容，未显式传入时生成稳定的实例 `plan_id`。
- `BaselineFindingPacket` 尾部新增 `claim_ids`、`search_log`、`limitations` 三个默认空列表字段，现有构造调用无需修改。

## 测试命令与原始结果摘要

1. RED 验证

   命令：`python3 -m pytest tests/equipment_deep_research/unit/test_domain_contracts.py -q`

   结果：退出码 2；测试收集按预期失败，原始关键错误为 `ModuleNotFoundError: No module named 'equipment_deep_research.domain.messages'`，`1 error in 0.04s`。

2. 领域契约测试

   命令：`python3 -m pytest tests/equipment_deep_research/unit/test_domain_contracts.py -q`

   结果：退出码 0；`7 passed in 0.01s`。

3. brief 指定回归测试

   命令：`python3 -m pytest tests/test_deep_research_runner.py -q`

   结果：退出码 0；`8 passed in 0.13s`。

4. 全量回归测试

   命令：`python3 -m pytest -q`

   结果：退出码 0；`15 passed in 0.11s`。

5. 编译检查

   命令：`python3 -m compileall -q src/equipment_deep_research/domain tests/equipment_deep_research/unit/test_domain_contracts.py`

   结果：退出码 0；无错误输出。

6. Diff 格式检查

   命令：`git diff --check`

   结果：退出码 0；无错误输出。

## 提交哈希

- 实现与测试：`f8013c87c1636c00b964e7df2ff6ae63411dc4c7`

## 自审

- 范围：仅修改用户授权的三个领域文件和一个单元测试文件；未修改同目录导出接口。
- 兼容：已有 `BaselineFindingPacket` 关键字构造、位置字段顺序及 provider 的 `__dict__` 重建方式保持兼容。
- 就绪语义：只有 `pending` 节点可就绪；全部依赖必须存在且状态为 `completed`；输出保持输入节点顺序。
- 传输约束：新增对象只包含字符串、整数、列表、字典等可投影为 JSON 的值；UTC 和 schema 约束由单元测试覆盖。
- 并发工作区：提交前未发现目标文件中的外部并发修改或未授权文件变更。

## 关注点

- 无阻断关注点。JSON 传输沿用仓库既有 `to_plain()` 投影约定，而不是直接对 dataclass 实例调用 `json.dumps()`。

## 审查修复

### 修复说明

- 在 `BaselineFindingPacket` 所有既有字段之后追加 `schema_version: str = "1.0"`，不改变旧位置参数顺序，也不要求既有关键字构造传入新参数。
- 将 `BaselineFindingPacket` 纳入跨进程传输元数据测试，覆盖稳定 `packet_id`、UTC ISO `created_at`、`schema_version` 和 JSON 序列化。
- `_assert_transport_metadata` 改为接收 ID 字段名，从对象读取对应属性，并断言序列化 payload 中同名 ID 非空且与对象属性一致。

### RED 验证

命令：`python3 -m pytest tests/equipment_deep_research/unit/test_domain_contracts.py -q`

结果：退出码 1；`1 failed, 6 passed in 0.02s`。唯一失败为 `BaselineFindingPacket` 传输元数据缺失，原始关键错误为 `KeyError: 'schema_version'`。

### 修复后覆盖测试

命令：`python3 -m pytest tests/equipment_deep_research/unit/test_domain_contracts.py -q`

结果：退出码 0；`7 passed in 0.01s`。

命令：`python3 -m pytest tests/test_deep_research_runner.py -q`

结果：退出码 0；`8 passed in 0.12s`。

### 附加回归与自审

命令：`python3 -m pytest -q`

结果：退出码 0；`15 passed in 0.11s`。

命令：`git diff --check`

结果：退出码 0；无错误输出。

- 修复限定在授权的模型、领域契约测试和任务报告文件；检查时未发现需要合并的他人并发修改。
