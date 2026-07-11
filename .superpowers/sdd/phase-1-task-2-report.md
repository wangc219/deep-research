# Phase 1 Task 2 Report

## 交付范围

- 新增 `JsonlSessionStore`：严格 JSON、append-only、进程内线程安全、拒绝 symlink、每次 append 后 `fsync`，提供 `read_all()`、`read_tail()` 与 `tail()`。
- 在保留现有 `DomainStore` / `TraceStore` API 的前提下新增 `SqliteRunStore`。
- `freeze_plain()` 拒绝 `NaN`、`Infinity`、`-Infinity`；所有新旧 JSONL 导出均使用 `allow_nan=False`。
- 未修改 Phase 0 runner 或 orchestration 调用路径。

## SQLite Schema

`domain_objects`

- 主键：`(run_id, object_type, object_id)`。
- 保存严格 JSON `payload_json`，并将 payload 的 `schema_version`、`created_at` 同步存列。
- 保存最后写入的 `proposal_id`、`idempotency_key` 与事务更新时间。

`trace_events`

- SQLite 全局 `sequence INTEGER PRIMARY KEY AUTOINCREMENT`。
- `run_sequence` 在单个 run 内严格单调，唯一约束为 `(run_id, run_sequence)`。
- `(run_id, proposal_id)` 唯一，保存 event type、actor、严格 JSON payload、创建时间和 schema version。

`savepoints`

- `checkpoint_id` 主键。
- `(run_id, ordinal)` 与 `(run_id, request_fingerprint)` 唯一。
- 保存排序后的 proposal key 集合与创建时间；同一 proposal 集不受输入顺序影响。

`proposal_ledger`

- 主键：`(run_id, key_kind, key_value)`。
- 分别记录全局 proposal ID 和 domain idempotency key 的内容 hash，用于区分“完全重复”与“同 key 内容冲突”。

数据库连接设置：WAL、`busy_timeout=5000ms`（可配置）、foreign keys；每次公开操作使用独立连接，避免跨线程共享 connection。

## 事务算法

1. 在打开写事务前，将全部 domain/trace proposals 转为普通数据并完整验证。
2. domain proposal 必须使用受支持 `object_type` 对应的稳定 ID 字段；当前覆盖 `ResearchProblem`、`EvidenceCard`、`BaselineFindingPacket`、`RecallRequest`、`AgentRecommendation`、`WinningMechanismStageOutput`、`CapabilityImageItem`、`AuditResult`、`ResearchReport`。
3. 拒绝未知类型、缺失/空对象 ID、缺失 schema version、无时区 created at、非法 operation 和非严格 JSON；对象 ID 从 payload 解析，不回退到 idempotency key。
4. 对排序后的 proposal 集计算稳定 request fingerprint 和 checkpoint ID。
5. 执行 `BEGIN IMMEDIATE`；若 fingerprint 已存在，提交只读事务并返回原 checkpoint。
6. 在 ledger 中检查 proposal ID/idempotency key：相同内容跳过重复写，不同内容抛出 `StoreConflictError`。
7. 写 domain objects，再分配并写 run 内单调 trace sequence，再写 savepoint 和 ledger。
8. 任一异常均在连接关闭前 rollback；只有全部步骤成功才 commit。

## RED / GREEN

RED：

```text
python3 -m pytest tests/equipment_deep_research/unit/test_store_savepoint.py tests/equipment_deep_research/unit/test_runtime_types.py -q
ImportError: cannot import name 'SqliteRunStore'
```

Task 1 minor RED：

```text
python3 -m pytest tests/equipment_deep_research/unit/test_runtime_types.py -q -k 'non_finite or strict_json'
3 failed, 1 passed
```

GREEN（最终聚焦）：

```text
python3 -m pytest tests/equipment_deep_research/unit/test_store_savepoint.py tests/equipment_deep_research/unit/test_runtime_types.py -q
35 passed
```

全量回归：

```text
python3 -m pytest -q
126 passed
```

原基线为 105 passed，本任务新增 21 项且未损失既有测试。

JSONL export：

```text
python3 -m pytest tests/equipment_deep_research/unit/test_store_savepoint.py -q -k export
2 passed, 15 deselected
```

## 并发、幂等与 Rollback

- 四个独立 `SqliteRunStore` 实例并发提交相同 proposal 集，返回同一 checkpoint，最终只有 1 个对象和 1 条 trace。
- 相同 proposal 集即使输入顺序变化也返回同 checkpoint。
- 相同 proposal ID 或 idempotency key 携带不同内容时显式失败，已有数据保持不变。
- append 在事务中途撞到既有对象时，之前已执行的 domain write、待写 trace、savepoint 和 ledger 全部回滚。
- trace conflict 在写入前由 ledger 检出；持久化 trace 可通过 `trace_events(after_sequence=...)` 增量读取，并通过 `last_trace_sequence()` / `recover()` 获得 run 内最后序号。

## JSONL 样例

Domain：

```json
{"payload":{"claim":"claim","created_at":"2026-07-11T00:00:00+00:00","evidence_id":"e1","schema_version":"1.0"},"type":"EvidenceCard"}
```

Trace：

```json
{"payload":{"actor":"agent-a","created_at":"<transaction UTC timestamp>","event_type":"evidence_saved","payload":{"evidence_id":"e1"},"proposal_id":"t1","run_id":"run-1","schema_version":"1.0","sequence":1},"type":"TraceEvent"}
```

每行均为单个 JSON object，写出使用 `allow_nan=False`。

## 依赖与自审

- `domain/store.py` 仅依赖 stdlib、domain models 和 proposals；`harness/session.py` 仅依赖 stdlib。
- 对目标文件扫描未发现对 `equipment_deep_research.orchestration` 的反向依赖。
- `python3 -m compileall -q src/equipment_deep_research`、`ruff check`、`git diff --check` 纳入最终提交前验证。
- 原子提交消息：`feat: add transactional run persistence`；实际提交哈希记录在最终交付回复中。
- 自审未发现阻断项。后续 Task 5 可在不移除现有 recover keys 的前提下扩展恢复摘要。

## 审查修复追加（2026-07-11）

### Rooted Session Path

- `JsonlSessionStore` 构造接口调整为 `JsonlSessionStore(path, root_dir=trusted_root)`；锁 key 使用 canonical root 与规范化 relative path。
- trusted root 先创建并 `resolve(strict=True)`，因此 `/tmp` 等系统级 symlink root 可作为显式受信入口；root 内部的任意祖先 symlink/junction 和最终文件 symlink 均拒绝。
- relative candidate 拒绝 `..`；absolute candidate 必须位于 requested root 或 canonical root 内，越界直接失败。
- POSIX 主路径用 root directory fd 锚定访问，逐组件执行 `stat(..., follow_symlinks=False)`、`mkdir(..., dir_fd=...)`、`open(..., dir_fd=..., O_DIRECTORY|O_NOFOLLOW)`；最终文件使用 `O_NOFOLLOW` 并以 `fstat` 对照 inode/device。
- 不提供完整路径式 fallback。缺少 `os.open/os.mkdir/os.stat` 的 dir fd 支持、`O_NOFOLLOW` 或 `O_DIRECTORY` 任一能力时，构造及每次 I/O 都以 `UnsupportedPlatformError` fail closed。
- 新测试覆盖祖先 symlink、最终 symlink、root 外 relative/absolute path、trusted root symlink、实际 `/tmp` resolved root、缺失安全能力 fail closed，以及 8 个 worker 并发执行 100 次 append。

### SQLite Zero-Write Preflight

- `BEGIN IMMEDIATE` 后先完成 request fingerprint、proposal ledger、idempotency ledger、同 batch object key 和 append target 的全部只读 preflight。
- preflight 生成最终 `domains_to_write` / `traces_to_write`；通过后才进入第一个 `INSERT`/`UPDATE` 循环。
- 同 batch 对相同 `(object_type, object_id)` 的不同有效 proposal 显式抛出 `StoreConflictError`；完全相同 idempotent proposal 仍去重。
- append 已存在目标的检查从 `_write_domain()` 移到 preflight。spy 测试确认 `[upsert-new, append-existing]` 失败时 `_write_domain()` 调用次数为 `0`；同 batch object 冲突同样为 `0`。

### 修复 RED / GREEN

RED：

```text
python3 -m pytest tests/equipment_deep_research/unit/test_store_savepoint.py -q
10 failed, 14 passed
```

关键 RED 证据：append conflict 前 `write_calls == 2`；同 batch object 未抛错；rooted session 新接口与安全测试全部失败。

GREEN：

```text
python3 -m pytest tests/equipment_deep_research/unit/test_store_savepoint.py -q
26 passed

python3 -m pytest -q
135 passed
```

质量检查：`ruff check`、`python3 -m compileall -q src/equipment_deep_research`、`git diff --check` 均通过；目标文件未出现 orchestration 反向依赖。

原子修复提交消息：`fix: harden session paths and store preflight`；实际提交哈希记录在最终交付回复中。

## Task 2 最终复审修复

- 删除 `_append_fallback`、`_read_lines_fallback`、完整路径 `lstat/open/fstat` fallback 及其路径快照逻辑。
- `JsonlSessionStore` 现在仅保留 root directory fd + per-component `dir_fd` 主路径。
- 新增 `UnsupportedPlatformError(RuntimeError)`。构造、`append()`、`read_all()` 均重新检查：
  - `O_NOFOLLOW` 非零；
  - `O_DIRECTORY` 非零；
  - `os.open`、`os.mkdir`、`os.stat` 均列于 `os.supports_dir_fd`。
- 任一能力缺失时，在打开 root 或目标前立即失败；不会创建候选父目录或目标文件。
- 参数化 I/O 测试在 store 构造后移除 dir fd 能力，并追踪 `os.open`：append/read 均抛明确错误，`open_calls == []`，目标文件不存在。

最终复审 RED：

```text
python3 -m pytest tests/equipment_deep_research/unit/test_store_savepoint.py -q -k jsonl_session
4 failed, 9 passed
```

最终复审 GREEN：

```text
python3 -m pytest tests/equipment_deep_research/unit/test_store_savepoint.py -q
29 passed

python3 -m pytest -q
138 passed
```

最终原子提交消息：`fix: fail closed without secure session primitives`；实际提交哈希记录在最终交付回复中。
