# Phase 0 Task 3 实施报告

## 结果

- 状态：DONE
- 实现提交：`fef977b6d556cb3028ca2dba979cee107ee7bcab` (`feat: define CLI run workspace contract`)
- CLI 已新增 `--provider-config`、`--evidence-config`、`--resume`、`--analyst-confirmed` 接口边界；其中恢复执行仍未实现。
- runner 使用 `RunWorkspace` 统一运行目录，并保持 scheduler 接收同一个 `run_dir`。
- 七类既有产物名称未改变；新增 `checkpoints/` 预留目录，Phase 0 不创建 `run.db`。

## 变更文件

- `src/equipment_deep_research/interfaces/cli.py`
- `src/equipment_deep_research/orchestration/runner.py`
- `src/equipment_deep_research/domain/workspace.py`
- `tests/equipment_deep_research/integration/test_cli_workspace.py`

## 实现说明

### 工作区

- `RunWorkspace.create(output_root, run_id)` 创建 `run_dir/`、`agent_sessions/`、`artifacts/`、`checkpoints/`。
- `database_path` 固定为 `run_dir / "run.db"`；Phase 0 不创建或接入 SQLite 数据库。
- 拒绝空白、绝对路径、包含 `..`、正反路径分隔符的 `run_id`。
- 创建目录前解析目标路径，并确认其父目录仍是解析后的 `output_root`，防止已有符号链接造成逃逸。

### CLI 与 runner

- provider/evidence 配置默认回退到项目内 `providers.yaml` 和 `evidence.yaml`，构造时保存为 `Path` 并校验文件存在。
- 新配置仅建立 CLI/runner 边界，本阶段不解析配置或接入真实 provider。
- `resume=True` 在任何运行目录副作用前精确抛出 `NotImplementedError("resume is enabled in Phase 1")`。
- `analyst_confirmed` 写入 `run_started` trace payload 和 `round_summary.json`，但不参与 Phase 0 审计或发布门控。
- 未修改 `AgentRegistry.select_agents()` 或增加 agent id 分支；默认四路仍由 registry 动态选择。

## RED

命令：

```text
python3 -m pytest tests/equipment_deep_research/integration/test_cli_workspace.py -q
```

结果：退出码 2，测试收集按预期失败；关键错误为：

```text
ModuleNotFoundError: No module named 'equipment_deep_research.domain.workspace'
1 error in 0.04s
```

## GREEN 与回归

Task 3 集成测试：

```text
python3 -m pytest tests/equipment_deep_research/integration/test_cli_workspace.py -q
14 passed in 0.14s
```

brief 指定 CLI 工作区与 runner 回归：

```text
python3 -m pytest tests/equipment_deep_research/integration/test_cli_workspace.py tests/test_deep_research_runner.py -q
35 passed in 0.31s
```

全量测试：

```text
python3 -m pytest -q
72 passed in 0.32s
```

附加检查：

- `python3 -m compileall -q ...`：退出码 0，无错误输出。
- `git diff --check`：退出码 0，无错误输出。

## Fake Smoke

使用独立输出根执行：

```text
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "低空无人机探测预警能力缺口" \
  --research-route auto \
  --run-id phase-0-smoke \
  --output-root /tmp/equipment-dr-phase0-smoke-task3
```

结果：退出码 0；`route=traditional_gap`，`audit_status=approved`。

产物清单：

- `report.md`：存在。
- `capability_images.json`：存在。
- `round_summary.json`：存在。
- `domain.jsonl`：存在。
- `trace.jsonl`：存在。
- `agent_sessions/`：存在，包含四个 registry 默认 agent 的 JSONL session。
- `artifacts/`：存在，包含四份 fake 材料及元数据。
- `checkpoints/`：存在且为空，等待 Phase 1 接入恢复点。

smoke 的 `round_summary.json` 显示四个默认 agent 为 `international_situation`、`combat_scenario`、`weapon_equipment`、`operational_employment`；`analyst_confirmed=false` 同时出现在 summary 和 `run_started` trace payload。

## 自审

- 所有权：实现仅修改用户授权的 CLI、runner、workspace 和集成测试；报告写入指定 SDD 路径。
- 兼容性：新增 runner 构造参数均有项目默认值，既有 `_runner` 调用无需改写；`run()` 新参数均有默认值。
- 路径安全：绝对路径、父目录、POSIX/Windows 分隔符和符号链接逃逸均在目录创建前被拒绝。
- 产物稳定性：七类既有名称和写入位置不变；只新增 `checkpoints/` 预留目录。
- 编排边界：scheduler 继续收到 `workspace.run_dir`，其既有 session/artifact 行为未重构。
- 配置边界：provider/evidence 配置只校验存在并保存路径，没有越界接入真实 provider。
- 标记语义：resume 不会静默忽略；analyst 标记可审计但不误作门控。
- 并发工作区：提交前工作树只包含本任务目标文件，未回退或覆盖其他工作者修改。

## 关注点

- `run.db` 在 Phase 0 仅有稳定路径，不创建数据库文件；SQLite 持久化和 resume 属于 Phase 1。
- provider/evidence 配置显式传入时只做存在性校验，结构解析和真实 provider 接线属于后续阶段。
- `analyst_confirmed` 当前仅记录，不阻断审计或发布，符合本阶段约束。

## 审查修复

### 修复内容

- 恢复旧 programmatic 构造兼容：省略 `provider_config_path`、`evidence_config_path` 时，只保存 `project_root` 下的默认路径，不因默认文件尚不存在而在构造阶段失败。
- 显式传入 provider/evidence 配置时继续要求 `is_file()`，不存在或不是文件均抛出 `FileNotFoundError`。CLI 会显式传入项目默认路径，因此 CLI 仍执行存在性校验。
- `run_id` 仅拒绝独立的 `.`、`..` 路径组件；路径分隔符和绝对路径仍单独拒绝，`release..1` 等普通标识可用。
- 新增真实符号链接逃逸回归：当 `output_root/run_id` 指向外部目录时抛出 `ValueError`，外部 marker 内容和目录成员均保持不变。

### RED

命令：

```text
python3 -m pytest tests/equipment_deep_research/integration/test_cli_workspace.py -q
```

结果：退出码 1；`2 failed, 16 passed in 0.12s`。

- `test_workspace_allows_double_dot_inside_run_id` 因旧 `".." in run_id` 检查失败。
- `test_runner_allows_omitted_new_configs_for_custom_project_root` 因省略参数后仍校验不存在的默认 provider 配置而失败。
- symlink 逃逸测试在 RED 阶段已通过，确认原有解析后父目录检查有效。

### GREEN 与回归

Task 3 集成测试：

```text
python3 -m pytest tests/equipment_deep_research/integration/test_cli_workspace.py -q
18 passed in 0.09s
```

审查指定回归：

```text
python3 -m pytest tests/equipment_deep_research/integration/test_cli_workspace.py tests/test_deep_research_runner.py -q
39 passed in 0.27s
```

全量测试：

```text
python3 -m pytest -q
76 passed in 0.32s
```

### Fake Smoke 复验

命令：

```text
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "低空无人机探测预警能力缺口" \
  --research-route auto \
  --run-id phase-0-task3-review \
  --output-root /tmp/equipment-dr-phase0-task3-review
```

结果：退出码 0；`route=traditional_gap`，`audit_status=approved`。运行目录包含七类既有产物及 `checkpoints/`。

### 修复自审

- programmatic 调用只有显式提供新配置时才承担文件存在性契约，省略参数维持 Phase 0 旧行为。
- CLI 参数始终显式转换为 `Path` 传入 runner，未绕过配置文件检查。
- `release..1` 不包含路径组件或分隔符，放行不会扩大目录逃逸面。
- 符号链接测试直接针对外部真实目录，验证拒绝发生后外部文件内容和成员集合不变。
- 未修改七类产物名、scheduler 目录传递、registry 动态默认 agent 选择、resume 或 analyst 标记语义。
