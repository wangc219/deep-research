# Phase 0 Task 2 实施报告

## 结果

- 状态：DONE
- 实现提交：`a308ff0` (`feat: unify research configuration`)
- 默认模型统一为 `gpt-5.5`。
- 公开来源不再按域名白名单阻断。
- 网络安全边界继续拒绝非 HTTP(S)、localhost、私网/保留 IP，以及解析到非公网地址的主机名。
- 抓取失败和网络安全拒绝材料保留诊断 artifact，但不进入正式证据集。

## 变更文件

### 主要所有权

- `configs/equipment_deep_research/agents.yaml`
  - 默认模型改为 `gpt-5.5`。
  - 四个默认 baseline agent 保持非空工具声明。
  - 上下文策略改用 `evidence_policy`，继续隐藏其他 agent 原始 session。
  - 增加对象读写 scopes；baseline 写 scope 固定为 `EvidenceCard`、`BaselineFindingPacket`、`WorkingCheckpoint`。
- `configs/equipment_deep_research/providers.yaml`
  - 新增默认 `responses` provider 和 `fake` provider；responses 模型为 `gpt-5.5`。
- `configs/equipment_deep_research/tools.yaml`
  - 新增结构化搜索 provider 和工具定义，覆盖所有 agent 已声明工具。
- `configs/equipment_deep_research/evidence.yaml`
  - 新增证据质量阈值、评分权重、去重、反证保留和网络安全配置。
- `configs/equipment_deep_research/source_whitelist.yaml`
  - 删除。
- `src/equipment_deep_research/agents/registry.py`
  - `AgentDef` 增加 `object_read_scopes`、`object_write_scopes`。
  - 加载 scopes，默认模型回退值改为 `gpt-5.5`。
- `tests/equipment_deep_research/unit/test_configuration.py`
  - 新增默认模型、baseline policy/scopes、证据阈值、provider 和工具配置契约测试。

### 最小支持性修改

- `src/equipment_deep_research/interfaces/cli.py`
  - 删除旧来源白名单 CLI 参数及传递；未增加 Task 3 的 provider/evidence/resume 参数。
- `src/equipment_deep_research/orchestration/runner.py`
  - 删除白名单路径、加载和 scheduler 注入。
  - 默认四路仍由 `AgentRegistry.select_agents()` 动态选择；未增加 `agent_id` 分支。
- `src/equipment_deep_research/harness/context.py`
  - 将旧来源白名单上下文改为质量门槛和失败材料隔离语义。
- `src/equipment_deep_research/harness/scheduler.py`
  - 删除白名单依赖；继续依据 `formal_evidence_allowed` 排除失败/拒绝材料。
- `src/equipment_deep_research/tools/materialization.py`
  - 删除域名白名单门控。
  - 公开 HTTP(S) 来源可正常抓取。
  - 保留协议、localhost、IP 和 DNS 解析结果的私网安全拒绝。
  - 抓取失败及安全拒绝诊断材料不进入正式证据。
- `src/equipment_deep_research/tools/source_policy.py`
  - 删除。
- `tests/test_deep_research_runner.py`
  - 将旧白名单断言替换为公开域名成功抓取、抓取失败隔离和私网预拒绝测试。
  - 自定义 agent 配置默认模型同步为 `gpt-5.5`。

支持性修改严格限于清除旧硬门控和保持安全/证据语义；未实现 Task 3 的 provider/evidence CLI 新参数、`RunWorkspace` 或 resume。

## RED

命令：

```text
python3 -m pytest tests/equipment_deep_research/unit/test_configuration.py -q
```

结果：`3 failed`。

- 默认模型实际为 `gpt-5.6-sol`，与期望 `gpt-5.5` 不符。
- `evidence.yaml` 不存在。
- `providers.yaml` 不存在；baseline scopes 尚未实现。

命令：

```text
python3 -m pytest tests/test_deep_research_runner.py -q -k 'public_source_is_not_blocked_by_domain or failed_public_fetch_is_not_formal_evidence'
```

结果：`2 failed, 7 deselected`。

- 成功公开来源和失败公开来源均先被旧域名门控标记为旧阻断状态，证明回归测试覆盖了待删除行为。

网络安全测试 RED：私网来源仍由旧白名单路径处理，未产生预期的 `network_safety_rejected`；后续 DNS 安全测试细化也在 materializer 尚无解析检查时失败。

## GREEN

配置测试：

```text
python3 -m pytest tests/equipment_deep_research/unit/test_configuration.py -q
...                                                                      [100%]
3 passed in 0.02s
```

公开来源、失败材料和私网安全目标测试：

```text
python3 -m pytest tests/test_deep_research_runner.py -q -k 'public_source_is_not_blocked_by_domain or failed_public_fetch_is_not_formal_evidence or private_network_source_is_rejected_before_fetch'
...                                                                      [100%]
3 passed, 7 deselected in 0.08s
```

## 残留扫描

命令：

```text
rg -n "gpt-5.6-sol|source_whitelist|allowed_domains|blocked_unapproved_source" src/equipment_deep_research scripts configs/equipment_deep_research tests/equipment_deep_research
```

结果：零命中，退出码 1（`rg` 在无匹配时的正常返回值）。

补充语义扫描：

```text
rg -n "source_policy|white_list_required|白名单|SourceWhitelist" src/equipment_deep_research scripts configs/equipment_deep_research tests
```

结果：零命中。

## 全量测试

命令：

```text
python3 -m pytest -q
....................                                                     [100%]
20 passed in 0.13s
```

另执行 `git diff --check`，零输出、退出码 0。

## 自审

- 默认四个 baseline agent 仍由 registry 动态返回，runner 未按 `agent_id` 分支。
- 四个 baseline agent 均有非空工具、上下文隔离开关、非空读 scope 和精确写 scope。
- 所有公开域名适用相同抓取路径，不存在批准域名集合或域名匹配逻辑。
- 网络安全判断基于 URL scheme、localhost、IP 属性和 DNS 解析结果，不是来源域名白名单。
- `fetch_failed` 与 `network_safety_rejected` 均设置 `formal_evidence_allowed: false`，scheduler 不会写入正式 EvidenceCard 集合，并会重写 finding packet 的 evidence IDs。
- provider、tool、evidence 配置均为结构化 YAML；provider 凭据只引用环境变量名。
- 未发现 Task 3 功能越界，也未发现他人修改需要回退。

## 关注点

- `evidence.yaml` 中响应大小和重定向上限在本任务中仅完成统一配置；完整配置驱动的抓取器限额执行属于后续网络证据阶段。
- 本任务按约束未把 provider/evidence 配置接入新的 CLI 参数，也未实现 `RunWorkspace` 或 resume。
