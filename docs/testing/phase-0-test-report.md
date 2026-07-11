# Phase 0 阶段测试报告

## 1. 结论

Phase 0 文档、测试基线、配置事实和运行产物契约已完成一致性复核。全量自动化测试通过，严格残留扫描零命中，独立输出根 smoke 成功生成七类稳定产物及 `checkpoints/` 预留目录。

当前已知限制：**真实模型循环和真实搜索尚未接入**。

## 2. 变更文件

- `README.md`
- `docs/TECHNICAL_SCHEME.md`
- `docs/ACCEPTANCE.md`
- `tests/test_deep_research_runner.py`
- `docs/testing/phase-0-test-report.md`
- `.superpowers/sdd/task-3-report.md`
- `tests/equipment_deep_research/integration/test_cli_workspace.py`
- `.superpowers/sdd/task-4-report.md`

## 3. 测试命令和精确结果

定向回归：

```text
python3 -m pytest -q tests/test_deep_research_runner.py tests/equipment_deep_research/integration/test_cli_workspace.py
.......................................                                  [100%]
39 passed in 0.29s
```

全量测试：

```text
python3 -m pytest -q
........................................................................ [ 94%]
....                                                                     [100%]
76 passed in 0.31s
```

严格一致性扫描：按 Task 4 brief 指定的四组退役表述和目标路径执行。

结果：零输出，退出码 1。`rg` 在无匹配时返回 1，符合预期。

## 4. Smoke 命令与结果

有效执行命令：

```text
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "低空无人机探测预警能力缺口" \
  --research-route auto \
  --run-id phase-0-smoke \
  --output-root /tmp/equipment-deep-research-phase-0-task-4.57nWVB
```

运行目录：

```text
/tmp/equipment-deep-research-phase-0-task-4.57nWVB/phase-0-smoke
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
- `providers.yaml`、`tools.yaml` 和 `evidence.yaml` 已建立配置边界，但 runner 尚未执行真实 Responses 模型循环、真实搜索或完整配置驱动质量评分闭环。
- `--resume` 只建立接口边界，恢复执行未实现。
- `run.db` 不创建；SQLite 持久化未实现。
- `checkpoints/` 仅预留目录，Phase 0 不写入恢复点。
- baseline scheduler 当前不是生产级并行 worker 架构。

## 6. Phase 1 进入条件

- 全量测试持续通过，严格一致性扫描保持零命中。
- 独立输出根 smoke 持续生成七类稳定产物和 `checkpoints/`。
- 默认模型、公开来源策略、失败材料隔离和 provider 边界在文档、配置、测试及代码中保持一致。
- Task 1-4 审查无阻断项，所有已知限制有明确后续归属。
- Phase 1 设计承诺兼容现有领域对象、CLI 参数、agent registry 和七类稳定产物契约。
- 真实 provider、搜索、持久化或恢复功能必须新增独立测试，不得以配置预留代替实现验证。

## 7. Task 1-4 审查结论摘要

- **Task 1：领域契约。** 任务消息、召回消息、研究计划节点与图、baseline packet 传输元数据已建立稳定 JSON 契约；审查修复已覆盖 schema、UTC 时间和稳定身份字段，无阻断项。
- **Task 2：配置与证据安全。** 默认模型统一为 `gpt-5.5`；公开来源不按域名准入；网络连接绑定已验证 IP，重定向逐跳复验；失败和安全拒绝材料与正式证据隔离，无阻断项。
- **Task 3：CLI 与工作区。** provider/evidence 配置、analyst 标记和 resume 接口边界已建立；七类产物保持稳定并新增 `checkpoints/` 预留；路径逃逸和兼容性修复已通过测试。恢复执行和 `run.db` 仍未实现，属于明确后续项。
- **Task 4：文档与阶段基线。** README、技术方案和验收说明已区分 Phase 0 与后续阶段；质量门控测试名称与断言语义一致；全量测试、扫描和 smoke 均达到 Phase 0 进入条件，无阻断项。
