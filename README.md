# 装备能力图像 Deep Research 多智能体系统

本项目面向装备能力图像需求生成，当前已完成 **Phase 0 可运行基线** 与 **Phase 1 harness/checkpoint 恢复闭环**。这些阶段仍只是甲方首版实施计划的基础，不等于甲方首版已经完成。

## Phase 0 已完成

- 支持三类研究路线：
  - `new_winning_mechanism`：新制胜机理、新体系组合、新作战样式牵引的新能力方向。
  - `traditional_gap`：传统场景和战法下的能力不足与装备升级需求。
  - `war_case_learning`：局部战争案例复盘牵引的未来能力布局方向。
- 提供四个默认 baseline agent：国际形势、作战场景、武器装备、作战运用。
- 四路 agent 是 registry 预设，可通过 `--agents` 选择子集，也可在 `configs/equipment_deep_research/agents.yaml` 中替换或新增。
- 支持制胜机理 L1 制胜逻辑、L2 概念创新、L3 能力图像三层输出。
- 输出包含能力编号、名称、装备类别、类型、来源制胜逻辑、关联场景、优先级、能力差距、能力画像九个字段。
- 默认模型配置为 `gpt-5.5`。
- 已实现广泛公开来源材料化、SSRF/网络安全拒绝和抓取失败隔离，不按来源域名设置准入门槛。
- agent 内部标识符使用受限 ASCII 契约，registry 和 session 路径边界都会拒绝路径分隔符、控制字符与 symlink 逃逸。
- `resume=False` 的每个 `run-id` 必须对应全新目录；已存在的空目录、非空目录或 symlink 都会在任何运行产物写入前被原子拒绝。

## Phase 1 已完成

- baseline agent 在 runner 中逐个执行；每个 agent 完成后，新增 `EvidenceCard`、`BaselineFindingPacket`、`TraceEvent` 与最新 `RunCheckpoint` 原子提交到 `run.db`。
- `RunCheckpoint` 保存 baseline tasks 与显式 `finalize:winning-report` task、run/task 状态、轮次、剩余预算、topic、请求/解析路线、所选 agent、来源材料、worker report、配置指纹、UTC 时间与 schema version。
- `--resume` 从最后已提交 savepoint 恢复 `DomainStore`、`TraceStore`、来源材料、worker report 和 session tail；已完成 agent 不重复执行，`pending/running` task 按原 agent 顺序继续。
- `ResearchProblem` 与初始 checkpoint 同事务持久化；恢复前先处理 `session_write_failed` reconciliation marker；旧 session 只追加，不重写。
- `RunWorkspace.open_existing()` 校验 run 目录、session、artifact、checkpoint 与 `run.db` 的类型、边界和 symlink 安全。
- completed resume 也先写 `run_resumed` trace/savepoint；正常完成返回 `status=completed`，数据库保存 finalize/run completed checkpoint，并继续生成七类稳定产物。
- `RunWorkspace` 从文件系统根逐组件安全打开 canonical output root，并在运行期持有 run、session、artifact、checkpoint 与 DB fd/inode；报告、JSON/JSONL、checkpoint、artifact 和 runner/recovery session 都从这些 handle 开始，拒绝已测试的 symlink/名称替换逃逸并在缺少安全原语时 fail closed。该保证以当前 UID 拥有、非 group/world writable 的私有 output root 为信任边界，不声称抵御持续操纵同 UID 私有 namespace 的本机恶意进程。
- runner/recovery 的 SQLite 使用安全 DB fd 绑定并持有单一连接，不按可变 run path 重连；安全 workspace 模式固定为 `journal_mode=MEMORY`、`synchronous=FULL`，拒绝遗留 WAL/SHM/journal sidecar。该模式不宣称具备 WAL 等价的掉电或进程被杀中途恢复保证。
- completed resume 提交 `run_resumed` 后始终从 SQLite 权威态重写稳定输出，provider 不重复执行，文件 trace 与数据库审计链一致。
- AgentHarness 的 wall-clock timeout、外部取消和 sibling failure 都有有界清理；不合作的进程内 provider/tool task 会被隔离并消费迟到异常，迟到结果不能再写 harness session、proposal、savepoint、domain state 或 RuntimeEvent。任意进程内代码已经开始的外部副作用无法由 asyncio 强制撤销，生产级强隔离需要子进程或远程 worker 边界。
- Harness 每次 execution 和 reconciliation 都确定性关闭 session handle；进程内 session path lock registry 在最后 owner 关闭后回收。EventBus 从 SQLite 权威 trace sequence 初始化，并在每次提交后继续前移，run 内 sequence 不因新实例或恢复而回退。
- 威胁与耐久性边界：受信 root 必须由当前 UID 控制且不位于 shared-writable namespace；实现不声称抵御恶意同 UID 进程持续竞速 `mkdir`/`open` 私有 namespace。SQLite 的单一持久 connection 与已提交 SQLite 状态是运行权威；安全 workspace 使用 MEMORY journal 且不留 sidecar，但不提供 WAL 等价的进程被杀或掉电耐久性保证。

## 当前实现边界

- `fake` 模式提供稳定的离线闭环，用于回归测试和交付演示。
- `real` 模式当前仍使用模板占位 provider，可对受控 URL 执行材料化并记录成功、失败或网络安全拒绝状态。
- 真实模型循环和真实搜索尚未接入。`providers.yaml` 和 `tools.yaml` 已预留 Responses-compatible provider 与搜索工具配置边界，但当前 runner 尚未加载并执行真实 Responses 模型循环或真实搜索 provider。
- `evidence.yaml` 已定义质量阈值以及相关性、透明度、时效性、直接支撑、提取质量五维权重，但 runner 尚未加载并执行质量评分。当前成功抓取的材料会进入正式证据，不能表述为已经经过运行时质量阈值门控。
- 新运行会创建 `run.db` 并在 `checkpoints/` 保存各 savepoint 快照与 `latest.json`；`--resume` 已可执行。
- 当前恢复粒度覆盖现有顺序 baseline agent 与后续 winning/report 闭环；AgentHarness 已提供有界进程内取消语义，但 runner 级暂停、真正并行调度、分布式 worker 和跨进程强制终止仍属后续阶段。
- `domain.jsonl`、`trace.jsonl` 和 `round_summary.json` 中实际持久化的领域对象包含稳定 ID、UTC `created_at` 与 `schema_version="1.0"`。
- 自定义 `project_root` 可省略尚未启用的 `providers.yaml` 与 `evidence.yaml`；配置指纹将“文件缺失”作为权威状态，文件后来出现时 resume 会因指纹变化而拒绝。

## 运行

离线闭环：

```bash
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "低空无人机探测预警能力缺口" \
  --research-route auto \
  --run-id fake-full
```

子集 agent：

```bash
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "低空无人机探测预警能力缺口" \
  --agents combat_scenario,weapon_equipment \
  --run-id fake-subset
```

Phase 0 real smoke：

```bash
python3 scripts/run_deep_research.py \
  --mode real \
  --topic "低空无人机探测预警能力缺口" \
  --research-route auto \
  --run-id real-smoke
```

`real` smoke 只验证占位 provider、受控 URL 材料化和失败材料隔离边界。公网不可达或网络安全校验拒绝时，系统会在 `artifacts/` 中保留诊断信息，并禁止失败材料进入正式证据集，不会伪造联网成功。

恢复已有运行：

```bash
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "低空无人机探测预警能力缺口" \
  --research-route auto \
  --run-id interrupted-run \
  --resume
```

恢复参数的 topic、路线、agent 集合和配置指纹必须与原运行一致。

## 当前证据行为

1. 广泛接收公开网络线索，不按域名预先筛除，并对公开 HTTP(S) URL 执行材料化。
2. 在网络层校验协议、目标地址、DNS 解析、重定向、响应大小和 TLS 边界，拒绝 SSRF 相关风险目标。
3. 抓取失败或网络安全拒绝的材料只保留诊断记录，不进入正式 `EvidenceCard` 支撑链。
4. 成功抓取的材料当前会进入正式证据；运行时尚未按 `evidence.yaml` 的质量阈值和五维权重评分。

## 甲方首版规划

- [装备能力图像 Deep Research 多智能体系统总实施计划](docs/superpowers/plans/2026-07-10-equipment-deep-research-master-plan.md)
- [装备能力图像 Deep Research 前后端一体化企业级设计方案](docs/superpowers/specs/2026-07-10-equipment-deep-research-frontend-backend-enterprise-design.md)

甲方首版仍需完成：真实模型循环、真实搜索、多轮研究、运行时质量评分、真正并行调度、Web 工作台和企业部署。当前七类产物、SQLite savepoint 与恢复边界是这些后续工作的基础，不是首版完成证明。

## 输出

新运行写入新的 `outputs/runs/<run-id>/`；只有显式 `--resume` 才可打开已有 run。七类稳定产物为：

- `report.md`：甲方可读能力画像报告。
- `capability_images.json`：能力画像结构化数据。
- `round_summary.json`：研究摘要、agent 覆盖、来源材料和 trace 摘要。
- `domain.jsonl`：领域对象流水。
- `trace.jsonl`：可审计事件链。
- `agent_sessions/`：所选 baseline agent 的独立会话。
- `artifacts/`：网页、正文、元数据或失败诊断材料。

同时创建 `run.db` 与 `checkpoints/`；它们用于事务 savepoint 与恢复，不替代七类稳定产物。

## 验证

```bash
python3 -m pytest -q
```

Phase 0 测试结论见 `docs/testing/phase-0-test-report.md`，Phase 1 测试结论见 `docs/testing/phase-1-test-report.md`，验收边界见 `docs/ACCEPTANCE.md`。
