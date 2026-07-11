# Phase 0 阶段测试报告

## 1. 结论

Phase 0 的最终整体审查修复已完成。除既有公开来源材料化、SSRF/网络安全拒绝和抓取失败隔离外，本轮已补齐 agent 内部标识符边界、run 目录原子独占语义，以及所有实际持久化 dataclass 的稳定 ID、UTC 时间和 schema 版本契约。`evidence.yaml` 已定义质量阈值与五维权重，但 runner 尚未加载执行质量评分，成功抓取目前会进入正式证据。Phase 0 只是甲方首版实施计划的基础阶段，不等于甲方首版完成。

当前已知限制：**真实模型循环和真实搜索尚未接入**。

## 2. 变更文件

- `src/equipment_deep_research/domain/identifiers.py`
- `src/equipment_deep_research/domain/models.py`
- `src/equipment_deep_research/domain/workspace.py`
- `src/equipment_deep_research/agents/registry.py`
- `src/equipment_deep_research/harness/scheduler.py`
- `tests/equipment_deep_research/unit/test_domain_contracts.py`
- `tests/equipment_deep_research/unit/test_configuration.py`
- `tests/equipment_deep_research/integration/test_cli_workspace.py`
- `tests/test_deep_research_runner.py`
- `README.md`
- `docs/TECHNICAL_SCHEME.md`
- `docs/ACCEPTANCE.md`
- `docs/testing/phase-0-test-report.md`
- `.superpowers/sdd/final-review-fix-report.md`

## 3. 测试命令和精确结果

领域契约：

```text
python3 -m pytest -q tests/equipment_deep_research/unit/test_domain_contracts.py
.........                                                                [100%]
9 passed in 0.06s
```

配置：

```text
python3 -m pytest -q tests/equipment_deep_research/unit/test_configuration.py
............                                                             [100%]
12 passed in 0.02s
```

CLI 工作区：

```text
python3 -m pytest -q tests/equipment_deep_research/integration/test_cli_workspace.py
....................                                                     [100%]
20 passed in 0.11s
```

runner：

```text
python3 -m pytest -q tests/test_deep_research_runner.py
.......................                                                  [100%]
23 passed in 0.26s
```

全量测试：

```text
python3 -m pytest -q
........................................................................ [ 79%]
...................                                                      [100%]
91 passed in 0.36s
```

严格一致性扫描一：扫描退役模型、白名单和旧拒绝状态。

结果：零输出，退出码 1。`rg` 在无匹配时返回 1，符合预期。

严格一致性扫描二：扫描 scheduler 直接拼接 agent session 路径、`run_dir` 的 `exist_ok=True` 复用和旧目录循环创建模式。

结果：零输出，退出码 1，符合预期。

编译检查：`python3 -m compileall -q src/equipment_deep_research tests/equipment_deep_research tests/test_deep_research_runner.py`，零输出，退出码 0。

## 4. Smoke 命令与结果

有效执行命令：

```text
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "低空无人机探测预警能力缺口" \
  --research-route auto \
  --run-id phase-0-smoke \
  --output-root /tmp/equipment-deep-research-phase-0-final.ScfUWB
```

运行目录：

```text
/tmp/equipment-deep-research-phase-0-final.ScfUWB/phase-0-smoke
```

关键状态：

- CLI 退出码：0。
- `mode`：`fake`。
- `resolved_route`：`traditional_gap`。
- `audit_status`：`approved`。
- 所选 agent：`international_situation`、`combat_scenario`、`weapon_equipment`、`operational_employment`。
- agent session 数量：4；四个 worker 状态均为 `completed`。
- `source_materials` 数量：4；状态均为 `fixture_materialized`。
- 正式证据数量：4；材料化证据数量：4。
- L1/L2/L3 stage output 数量：3。
- capability image 数量：2。
- `domain.jsonl` 六类领域对象均为 `schema_version="1.0"`，稳定 ID 非空。
- `trace.jsonl` 包含 11 条 `TraceEvent`，均为 `schema_version="1.0"`、稳定 ID 非空、UTC 时间。
- `round_summary.json` 的 `ResearchProblem` 和 4 条 `WorkerReport` 均包含稳定 ID、UTC 时间和 schema 版本。
- `checkpoints/`：存在且为空。
- `run.db`：不存在。

七类稳定产物清单：

- `report.md`
- `capability_images.json`
- `round_summary.json`
- `domain.jsonl`
- `trace.jsonl`
- `agent_sessions/`，包含 4 个 JSONL session。
- `artifacts/`，包含 4 份正文和 4 份元数据。

附加预留目录：`checkpoints/`。

## 5. 已知限制

- 真实模型循环和真实搜索尚未接入。
- Phase 0 `real` provider 仍为模板占位，只能生成受控公开 URL 线索并进入材料化流程。
- `providers.yaml`、`tools.yaml` 和 `evidence.yaml` 已建立配置边界；其中 `evidence.yaml` 已定义质量阈值和五维权重，但 runner 尚未加载执行质量评分，成功抓取目前会进入正式证据。
- `--resume` 只建立接口边界，恢复执行未实现。
- `run.db` 不创建；SQLite 持久化未实现。
- `checkpoints/` 仅预留目录，Phase 0 不写入恢复点。
- baseline scheduler 当前不是生产级并行 worker 架构。

## 6. Phase 1 进入条件

- 全量测试持续通过，严格一致性扫描保持零命中。
- 独立输出根 smoke 持续生成七类稳定产物和 `checkpoints/`。
- 默认模型、公开来源材料化、网络安全拒绝、失败材料隔离和 provider 配置边界在文档、配置、测试及代码中保持一致。
- 将运行时加载 `evidence.yaml`、执行五维质量评分并据此控制正式证据准入作为后续阶段明确进入条件。
- Task 1-4 审查无阻断项，所有已知限制有明确后续归属。
- Phase 1 设计承诺兼容现有领域对象、CLI 参数、agent registry 和七类稳定产物契约。
- 真实 provider、搜索、持久化或恢复功能必须新增独立测试，不得以配置预留代替实现验证。

## 7. Task 1-4 审查结论摘要

- **Task 1：领域契约。** 任务消息、召回消息、研究计划节点与图，以及所有实际持久化领域对象和 worker summary 已建立稳定 JSON 契约；新增字段均位于尾部并带默认值，旧构造兼容测试通过。
- **Task 2：配置与证据安全。** 默认模型统一为 `gpt-5.5`；公开来源不按域名准入；网络连接绑定已验证 IP，重定向逐跳复验；失败和安全拒绝材料与正式证据隔离。`evidence.yaml` 的质量阈值与五维权重属于已定义配置边界，运行时评分尚未接入。
- **Task 3：CLI 与工作区。** provider/evidence 配置、analyst 标记和 resume 接口边界已建立；`agent_id` 在 registry 与 scheduler 双重校验，session symlink 被拒绝；`resume=False` 原子拒绝任何已存在 run 目录，防止旧 session 污染。恢复执行和 `run.db` 仍未实现，属于明确后续项。
- **Task 4：文档与阶段基线。** README、技术方案和验收说明明确 Phase 0 只是甲方首版基础阶段；测试名称与“公共域名不被域名门控、成功抓取可材料化”的实际行为一致。配置边界已对齐，运行时质量评分是后续进入条件，不能作为 Phase 0 已完成能力。
