# Phase 0 Task 4 实施报告

## 结果

- 状态：DONE。
- 完成 README、技术方案、验收说明和阶段测试报告同步。
- 核对 Task 2 已提前实现的广泛公开来源材料化、SSRF/网络安全拒绝和抓取失败隔离测试，仅调整测试名称与现行语义一致。
- 修正 Task 3 报告两处过时结果表述，明确恢复执行未实现且 Phase 0 不创建 `run.db`。
- 全量测试通过，严格扫描零命中，独立 `phase-0-smoke` 成功。

## 变更文件

### 主要所有权

- `README.md`
- `docs/TECHNICAL_SCHEME.md`
- `docs/ACCEPTANCE.md`
- `tests/test_deep_research_runner.py`
- `docs/testing/phase-0-test-report.md`

### 支持性修改

- `.superpowers/sdd/task-3-report.md`
- `tests/equipment_deep_research/integration/test_cli_workspace.py`

### 实施报告

- `.superpowers/sdd/task-4-report.md`

## 文档同步

- 明确当前交付是 Phase 0 可运行基线，不是生产级真实 Deep Research 服务。
- 默认模型统一表述为 `gpt-5.5`。
- 公开来源运行行为统一表述为广泛公开来源材料化、网络安全拒绝和抓取失败隔离，不按域名设置准入门槛。
- `evidence.yaml` 的质量阈值和五维权重统一表述为配置边界；runner 尚未加载执行质量评分，成功抓取当前会进入正式证据。
- 明确 `real` provider 当前为模板占位，可执行受控 URL 材料化，但真实模型循环和真实搜索尚未接入。
- 明确四路 baseline agent 是 registry 预设，可选择子集、替换或新增。
- 明确七类产物稳定，`checkpoints/` 只作预留；resume、`run.db` 和 SQLite 持久化未实现。
- 将 Web/API、SSE、RBAC、数据库、队列、并行 worker 和企业部署移入后续阶段，未写成 Phase 0 已完成。

## 测试基线核对

- `tests/test_deep_research_runner.py` 已包含公开来源成功材料化、失败抓取隔离、私网拒绝、DNS 与连接 IP 绑定、重定向逐跳检查、响应限制、TLS 校验和 fixture 边界测试。
- 仅将公开来源测试改名为 `test_public_domain_fetch_is_materialized_without_domain_gate`，保留成功状态、正式证据数量和 baseline evidence IDs 断言。
- 将 CLI 集成测试函数改名为 `test_cli_exposes_provider_and_evidence_controls_without_domain_gate`，测试行为不变。
- 未引入旧来源配置字段、旧阻断状态或旧模型名。

## 定向验证

命令：

```text
python3 -m pytest -q tests/test_deep_research_runner.py tests/equipment_deep_research/integration/test_cli_workspace.py
```

结果：

```text
.......................................                                  [100%]
39 passed in 0.29s
```

## 严格扫描

命令：按 Task 4 brief 指定的四组退役表述，对 README、技术文档、源码、脚本、配置和测试执行 `rg -n` 扫描。

结果：零输出，退出码 1，符合无匹配预期。

## 全量测试

命令：

```text
python3 -m pytest -q
```

结果：

```text
........................................................................ [ 94%]
....                                                                     [100%]
76 passed in 0.31s
```

## Phase 0 Smoke

命令：

```text
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "低空无人机探测预警能力缺口" \
  --research-route auto \
  --run-id phase-0-smoke \
  --output-root /tmp/equipment-deep-research-phase-0-task-4.57nWVB
```

结果：退出码 0；运行目录为 `/tmp/equipment-deep-research-phase-0-task-4.57nWVB/phase-0-smoke`。

关键状态：

- route：`traditional_gap`。
- audit status：`approved`。
- 四个默认 baseline agent 全部 `completed`。
- agent session 数量：4。
- source material 数量：4，全部 `fixture_materialized`。
- 正式证据数量：4；材料化证据数量：4。
- stage output 数量：3；capability image 数量：2。
- 七类稳定产物全部存在。
- `checkpoints/` 存在且为空。
- `run.db` 不存在。

七类稳定产物：

- `report.md`
- `capability_images.json`
- `round_summary.json`
- `domain.jsonl`
- `trace.jsonl`
- `agent_sessions/`
- `artifacts/`

## Task 1-4 审查摘要

- Task 1 的领域消息、计划图和 baseline packet 传输契约已经审查修复，稳定身份、schema 与 UTC 时间均有自动化覆盖。
- Task 2 的默认模型、配置契约和公开材料安全边界已经多轮安全复审，公开来源统一进入安全材料化流程，失败材料不进入正式证据。
- Task 3 的 CLI 与工作区契约已经兼容性复审，七类产物保持稳定并新增 `checkpoints/` 预留；恢复执行和数据库仍明确延期。
- Task 4 已消除交付文档中的阶段混淆，建立可复现的全量测试、严格扫描和 smoke 证据包。

## Phase 1 进入条件

- 保持 76 项全量测试和严格扫描基线通过。
- 保持 `phase-0-smoke` 七类产物、四路 agent session 和 `checkpoints/` 契约稳定。
- 为真实 Responses 模型循环、真实搜索、质量评分闭环、checkpoint、数据库和 resume 分别增加独立实现与测试。
- 不得把配置文件、CLI 参数或预留目录当作功能已经接入的证明。
- 后续改动必须兼容现有领域对象、agent registry、CLI 和输出文件名称。

## 已知限制

真实模型循环和真实搜索尚未接入。

此外，Phase 0 不提供持久化 checkpoint、`run.db`、resume、生产级并行 worker、Web/API、权限和部署能力。

## 自审

- 修改范围限定在用户授权文件和指定实施报告。
- 未回退或覆盖其他工作者修改；开始任务时工作树干净。
- `tests/test_deep_research_runner.py` 未重复实现 Task 2 行为，只做必要命名一致性修改。
- 文档中所有 Phase 0 完成声明均可在当前代码、测试或 smoke 产物中定位。
- 后续 Phase 1+ 能力均明确标记为未实现或后续进入条件。

## 审查修复：文档真实性

### 修复内容

- README、技术方案、验收说明、阶段测试报告和本实施报告统一为当前运行时事实：Phase 0 已实现广泛公开来源材料化、SSRF/网络安全拒绝和抓取失败隔离。
- 明确 `evidence.yaml` 已定义质量阈值以及相关性、透明度、时效性、直接支撑、提取质量五维权重，但 runner 目前只保存并校验配置路径，尚未加载执行质量评分。
- 明确成功抓取的材料当前设置为可进入正式证据；不得声称运行时质量阈值门控已经完成。
- 将公开来源测试改名为 `test_public_domain_fetch_is_materialized_without_domain_gate`，保留 `fetched`、正式证据数量和 baseline evidence IDs 断言。
- 三份主文档明确 Phase 0 只是甲方首版实施计划的基础阶段，不等于甲方首版完成。
- 三份主文档恢复总实施计划和前后端企业级设计方案入口，并列明首版仍需真实模型循环、真实搜索、多轮研究、运行时质量评分、并行调度与恢复、Web 工作台和企业部署。
- 阶段测试报告的结论、进入条件和 Task 4 摘要改为“配置边界已一致，运行时评分是后续进入条件”。

### 定向测试

命令：

```text
python3 -m pytest -q tests/test_deep_research_runner.py -k public_domain_fetch_is_materialized_without_domain_gate
```

结果：

```text
.                                                                        [100%]
1 passed, 20 deselected in 0.16s
```

### 全量测试

命令：

```text
python3 -m pytest -q
```

结果：

```text
........................................................................ [ 94%]
....                                                                     [100%]
76 passed in 0.36s
```

### 严格扫描

按 Task 4 brief 指定的四组退役表述和目标路径执行扫描。结果为零输出、退出码 1，符合无匹配预期。

### Smoke 决策

本次只修改文档和测试函数名称，断言与运行行为未变化，因此按审查要求未重跑 smoke。此前独立 `phase-0-smoke` 的七类产物、4 个 agent sessions、空 `checkpoints/` 和关键状态记录继续作为 Phase 0 运行基线。
