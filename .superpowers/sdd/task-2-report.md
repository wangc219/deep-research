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

## 安全审查修复

### 设计

- 新增 `src/equipment_deep_research/tools/http_transport.py`，使用 Python 标准库 `http.client`、`socket`、`ssl` 实现受控传输，无新增第三方依赖。
- materializer 对初始 URL 和每个 `Location` 跳转分别解析 hostname，校验解析结果全部为公网 IP 后，只把选中的数值 IP 交给传输层。
- 传输层直接对数值 IP 创建 TCP socket，不再自由解析 hostname；HTTP `Host`、HTTPS SNI 和证书 hostname 校验仍使用 URL 原 hostname。
- TLS context 强制 `check_hostname=true` 且 `verify_mode=CERT_REQUIRED`，不能通过 IP 绑定关闭证书校验。
- `http.client` 不自动跟随重定向；materializer 手动处理 `301/302/303/307/308`，每跳重新解析、验证和绑定，最多跟随 5 跳。私网或保留地址在进入 transport 前返回 `network_safety_rejected`。
- fixture 仅在 scheme 为 HTTP(S)、`mode == "fake"` 且解析后的 hostname 精确等于 `fixture.local` 时离线材料化；real 模式拒绝，userinfo 形式按实际 hostname 进入公开来源路径。
- 保持 `fetch_failed` 与 `network_safety_rejected` 的正式证据隔离语义；未增加 Task 3 CLI、provider 接线、workspace 或 resume 功能。

### RED

安全回归测试首次运行：

```text
python3 -m pytest tests/test_deep_research_runner.py tests/equipment_deep_research/unit/test_configuration.py -q
....FFFFFFFFF......                                                      [100%]
9 failed, 10 passed in 0.15s
```

失败原因符合预期：原 materializer 不支持可注入 resolver/transport，也不存在绑定 IP 的 `PinnedHTTPTransport`；因此无法锁定 DNS 结果与 TCP 目标、逐跳拒绝私网重定向或 fixture mode 边界。

补充 fixture scheme 回归测试首次运行：

```text
python3 -m pytest tests/test_deep_research_runner.py -q -k 'fake_fixture_does_not_bypass_allowed_schemes'
F                                                                        [100%]
1 failed, 19 deselected in 0.08s
```

失败证明重构中的 fixture 快路径一度会绕过 HTTP(S) scheme 限制；随后调整判断顺序修复。

### 测试覆盖

- 直接私网 IP 在 transport 前拒绝。
- DNS 返回的已验证公网 IP 与 transport 收到的 `connect_ip` 完全一致。
- 公网响应重定向到私网 hostname 时，第二跳在 transport 前拒绝，transport 只收到首个公网 IP 请求。
- 重定向跳数达到上限后隔离为 `fetch_failed`。
- pinned HTTPS 使用已验证 IP 建立连接，同时以原 hostname 执行 SNI；不接受关闭证书 hostname 校验的 TLS context。
- fake fixture 精确 hostname 成功；real fixture 拒绝；`https://fixture.local@attacker.com/` 按 `attacker.com` 处理，不伪装 fixture。
- 公开来源成功材料化和 `fetch_failed` 正式证据隔离继续通过。
- evidence acceptance、weights、deduplication、contradiction、network_safety 全部精确值已由配置测试锁定。
- 自定义 agent registry 在未显式传入 `agent_ids` 时动态选择自定义 baseline。

### GREEN 与全量验证

配置测试：

```text
python3 -m pytest tests/equipment_deep_research/unit/test_configuration.py -q
...                                                                      [100%]
3 passed in 0.02s
```

runner 与安全测试：

```text
python3 -m pytest tests/test_deep_research_runner.py -q
....................                                                     [100%]
20 passed in 0.24s
```

全量测试：

```text
python3 -m pytest -q
..............................                                           [100%]
30 passed in 0.24s
```

另执行 `git diff --check`，零输出、退出码 0。

### 安全修复关注点

- 受控传输刻意不使用环境 HTTP(S) 代理，因为经普通代理无法证明目标 TCP 连接绑定到本地已验证 IP；必须依赖强制代理的环境会得到隔离的 `fetch_failed`，后续如需代理支持应设计同等可验证的受控代理协议。
- 当前重定向和响应大小上限使用与 `evidence.yaml` 一致的安全默认值；将其动态加载为运行时配置仍属于后续配置接线，不在本次 Task 2 修复范围内。

## 安全复审二次修复

### 显式公网单播判定

- 不再使用 `ipaddress.is_global` 作为准入判定。
- IPv4 显式拒绝 private、loopback、link-local、unspecified、reserved、multicast 和 shared address space (`100.64.0.0/10`)。
- IPv6 显式拒绝 private、loopback、link-local、unspecified、reserved、multicast、site-local 和带 zone identifier 的地址。
- IPv4-mapped、IPv4-translated、6to4、Teredo、NAT64 well-known 和 ISATAP 地址提取其嵌入 IPv4，并复用同一 IPv4 公网单播判定。
- NAT64 local-use `64:ff9b:1::/48` 的嵌入位置不能仅凭地址可靠确定，因此对整个前缀保守拒绝。
- literal 与 DNS 返回地址均调用同一个 `_is_public_unicast_address()`；DNS 结果中任一地址不合格即在 transport 前拒绝整跳。

### URL 与 hostname 隔离

- `_parse_network_url()` 统一处理 `urlsplit`、scheme、hostname、port 和 IDNA；初始 URL 与每个重定向 URL 使用同一路径。
- hostname 在 fixture 判断、DNS resolver、transport、HTTP `Host` 和 HTTPS SNI 前统一转换为小写 IDNA ASCII。
- 畸形 IPv6 URL、无效 port 或 IDNA 编码失败均产生单条 `network_safety_rejected` 诊断，不再抛出到 scheduler 导致整个 agent 跳过。

### RED

首次执行新增覆盖：

```text
python3 -m pytest tests/equipment_deep_research/unit/test_http_transport.py tests/equipment_deep_research/unit/test_configuration.py tests/test_deep_research_runner.py -q
FF.F...FFF..FF..............F.............                               [100%]
9 failed, 33 passed in 0.37s
```

失败覆盖：`fec0::1`、NAT64 loopback 映射和 multicast literal/DNS 被错误放行；畸形 IPv6 URL 抛出到 scheduler；Unicode hostname 未转换为 IDNA ASCII。

无效 IDNA 定向测试首次执行：

```text
python3 -m pytest tests/equipment_deep_research/unit/test_http_transport.py -q -k 'invalid_idna_hostname or invalid_port'
F.                                                                       [100%]
1 failed, 1 passed, 18 deselected in 0.08s
```

带 zone identifier 的公网 IPv6 定向测试首次执行为 `1 failed`，证明其会进入 transport；随后纳入保守拒绝。

### 底层传输测试

新增 `tests/equipment_deep_research/unit/test_http_transport.py`，覆盖：

- site-local、NAT64 well-known/local-use、multicast、IPv4-mapped、IPv4-translated、6to4、Teredo、ISATAP 和 scoped IPv6 的 literal/DNS 拒绝。
- 正常公网 IPv4/IPv6 literal 仍进入 pinned transport。
- IDNA hostname 同时传给 resolver 和 transport。
- numeric connect 对 IPv4 选择 `AF_INET`、对 IPv6 选择 `AF_INET6`。
- IDNA hostname 与非默认端口的 `Host` header，以及 IPv6 Host 方括号格式。
- 响应超过字节上限时抛出 `HTTPResponseTooLarge`，并在异常路径关闭连接。
- 畸形 IPv6 URL 在直接 materializer 和 runner/scheduler 集成路径均只产生隔离诊断。

### 最终验证

复审指定覆盖命令：

```text
python3 -m pytest tests/equipment_deep_research/unit/test_http_transport.py tests/equipment_deep_research/unit/test_configuration.py tests/test_deep_research_runner.py -q
...................................................                      [100%]
51 passed in 0.30s
```

全量测试：

```text
python3 -m pytest -q
..........................................................               [100%]
58 passed in 0.29s
```

另执行 `git diff --check`，零输出、退出码 0。
