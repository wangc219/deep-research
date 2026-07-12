# Phase 1 Task 5 实施报告

## 交付结论

Task 5 已将 checkpoint 恢复接入现有 runner/CLI，并保持 Phase 1 不伪造 Phase 2 真实模型能力。

## 实现摘要

- 新增稳定 `RunCheckpoint`，保存 run/task 状态、round、budget、topic/route/agents、source materials、worker reports、配置指纹、resume count、UTC 时间和 schema。
- `SqliteRunStore` 支持 `RunCheckpoint`，并提供领域对象读取用于恢复；`DomainStore` 可恢复 problem/evidence/packet/recall/recommendation/stage/image/audit/report。
- 新增 `RunWorkspace.open_existing()`，拒绝缺失、类型错误、顶层 symlink 和 root 外逃逸。
- 新增 `RecoveryManager.load(run_id)`：先处理 reconciliation marker，再恢复最后 checkpoint、领域态、trace、来源材料、worker report 与 session tail；topic/route/agents/config 不匹配明确失败。
- runner baseline agents 改为逐 agent 执行。task 开始保存 `running` checkpoint；task 完成时新增 evidence、packet、trace 和 completed task checkpoint 原子提交。
- 初始事务持久化 `ResearchProblem`，checkpoint 显式包含 `finalize:winning-report`；最后 baseline 后 finalize 保持 pending，engine 前提交 finalize running，最终领域对象与 finalize/run completed checkpoint 同事务提交。
- runner 构造器允许注入兼容 `AgentProvider`，用于 crash 测试；异常继续传播，之前已提交状态保持可恢复。
- resume 只重排 pending/running task，跳过 completed baseline；running finalize 会重新执行。completed resume 也先追加 `run_resumed` trace/savepoint，但不调用 provider。
- scheduler 使用 rooted `JsonlSessionStore`。DB commit 后 session savepoint 失败会自动提交 `session_write_failed` marker；恢复补 recovered savepoint 与幂等 `session_reconciled` 后才跳过 completed task。
- `RunWorkspace` 新增 dirfd 原子 writer，最终输出和 checkpoint latest/history 不再裸写；leaf symlink、检查后替换和缺失安全原语均 fail closed。
- 正常完成将 winning/report 领域对象、trace 与 completed checkpoint 写入 `run.db`，继续输出七类稳定产物，result 增加 `status=completed`。
- CLI 的 `--resume` 已实际执行恢复；输出增加 status，同时兼容旧式 runner 测试替身未返回 status 的情况。

## RED / GREEN

初始 RED：

```text
python3 -m pytest tests/equipment_deep_research/e2e/test_resume_run.py -q
ModuleNotFoundError: No module named 'equipment_deep_research.harness.recovery'
```

GREEN：

```text
python3 -m pytest tests/equipment_deep_research/e2e/test_resume_run.py -q
21 passed

python3 -m pytest \
  tests/equipment_deep_research/e2e/test_resume_run.py \
  tests/equipment_deep_research/integration/test_agent_harness.py -q
50 passed

python3 -m pytest -q
222 passed

最终安全 stat race 补强后：workspace writer/stat 8 passed；resume E2E + domain contracts 30 passed。
```

## 第二轮审查修复

- 新增项目自有 `SecureArtifactStore`，保持旧 `ArtifactStore` 的 content-addressed ref、扩展名和 metadata schema；runner 的 `EvidenceMaterializer` 通过 `RunWorkspace` 从 run dirfd 逐组件打开 `artifacts/`，不再裸写 artifact 路径。
- `JsonlSessionStore` 新增显式 `anchor_dir`，同时保留 Harness 使用的 `path + root_dir` 接口。runner/recovery 以 canonical output root 为锚，逐组件 no-follow 打开 `run_id/agent_sessions/session_ref`，不再把可变 `agent_sessions.resolve()` 当信任根。
- completed resume 在提交 `run_resumed` 后，无条件使用 SQLite 恢复的 domain/trace/checkpoint 状态安全重写五个稳定文件；`trace.jsonl` payload 与数据库 trace payload 保持一致，provider 调用仍为 0。
- 新增 artifact/session ancestor 替换 TOCTOU、reconciliation 外写阻断、安全原语缺失、SecureArtifactStore 兼容 metadata、completed resume 陈旧文件与审计链刷新测试。

本轮 fresh 结果：resume E2E `24 passed`；resume E2E + Harness `53 passed`；材料化/安全 artifact `52 passed`；Phase 0 组合 `72 passed`；全量 `229 passed`。

## 最终复审根锚定修复

- `RunWorkspace.create/open_existing` 先把 output root 转为 canonical 绝对路径，再从文件系统根开始逐组件 `O_DIRECTORY|O_NOFOLLOW` 打开并比对 `lstat/fstat` identity；run、`agent_sessions`、`artifacts`、`checkpoints` 和 `run.db` 均通过 dirfd 原子创建或打开。
- workspace 生命周期内持有 run、三个子目录和 DB 的私有 fd，公开 `dup_*_fd()` 与幂等 `close()`；rooted writer 从绑定 fd 的 `dup()` 开始，不再通过 `os.open(self.root_dir)` 重开路径。runner 正常、崩溃和恢复失败路径均在 `finally` 关闭 SQLite/workspace 资源。
- `SecureArtifactStore` 的 runner 路径只调用 workspace fd API；`JsonlSessionStore` 新增 `root_fd` handle 接口，runner scheduler/recovery 只传 workspace dup 的 sessions fd，Harness 原 `path + root_dir` 接口保留。
- runner/recovery 的 `SqliteRunStore` 使用 workspace 安全打开的 DB fd，解析绑定 inode 的当前路径并在写入前校验 identity，之后生命周期内复用一个持久 SQLite 连接，不再按可变 run path 重连。
- 新增 output root 被替换为 symlink/普通目录、run dir 和三个子目录被替换、reconciliation open 后 root 替换、异常资源关闭与安全原语缺失测试。所有 checkpoint/output/artifact/session/DB 写入只落到原绑定目录或 fail closed，攻击者目录无文件。

最终 fresh 结果：resume E2E `29 passed`；resume E2E + Harness `58 passed`；materialization/artifact `52 passed`；store `33 passed`；Phase 0 组合 `79 passed`；全量 `243 passed`。

## Smoke

fresh smoke：`status=completed`、ResearchProblem=1、finalize completed、stage=3、report=1；七类产物、`run.db`、checkpoint snapshots 与 `latest.json` 齐全。

crash+resume smoke 覆盖 agent 中途、最后 baseline 后、engine 后最终事务前三个窗口。恢复分别只执行剩余 baseline 或仅 finalize；domain/trace key 唯一、`run_resumed=1`、completed checkpoint 与七类产物齐全。completed resume provider=0 且仍写审计 trace/savepoint。

## 文档

- 新增 `docs/testing/phase-1-test-report.md`，记录 schema、session、崩溃点、恢复结果、测试和真实 provider 未接入边界。
- 更新 README、技术方案和验收说明，从 Phase 0 的 resume 预留状态切换到 Phase 1 当前实现。
- Phase 1 Task 2 Ruff 证据范围更正为目标文件范围，不表述为全仓库 Ruff。

## 关注点

- 当前恢复粒度是现有顺序 baseline agent 与 winning/report 闭环，不宣称真正并行或分布式恢复。
- checkpoint JSON 文件是审计快照，SQLite `run.db` 是恢复权威来源。
- 安全 artifact/session 路径依赖 `O_NOFOLLOW`、`O_DIRECTORY` 与 dirfd 操作；平台缺少这些原语时明确 fail closed。
- SQLite fd 绑定路径解析当前支持 macOS `F_GETPATH` 与 Linux `/proc/self/fd`；缺失时 fail closed。遭遇恶意 rename 后，返回结果中的路径字符串可能不再指向绑定 inode，安全写入权威始终是持有 fd。
- `RealAgentProvider` 仍为模板占位，真实模型循环和真实搜索属于 Phase 2。

## 最终复审修复

### Reviewer finding 验证

六项 finding 均在 `f90741c` 上确认有效，没有因可移植性或正确性原因驳回的项：

- `RunWorkspace.create` 原实现的 `mkdir(run_id)` 与首次 `lstat/open` 之间确实可接受攻击者替换的普通目录。现改为随机临时目录先打开并绑定 inode，再通过 macOS `renameatx_np(RENAME_EXCL)` 或 Linux `renameat2(RENAME_NOREPLACE)` 原子发布；原语缺失时 fail closed。确定性竞争测试证明目标名被攻击者抢占时不绑定、不修改攻击者目录，并清理临时目录。
- Python 标准库 SQLite 不能直接从既有 fd 打开带 WAL 的数据库；`F_GETPATH`/`/proc/self/fd` 反解路径后的 pathname stat 不能证明 SQLite 实际打开的 handle。正确替代是在保留持久连接与 WAL 语义的同时，使用 `mode=rw` 禁止错误 namespace 创建 DB，在任何 schema 写入前审计进程 fd 表并匹配绑定 DB inode；runner/recovery 同时传入绑定 run-dir fd，WAL/SHM 必须由该目录的 regular-file inode 且由进程持有。SQLite 的 POSIX 同 inode fd 复用只在绑定目录已有打开的 WAL/SHM 时接受。macOS 使用 `/dev/fd`，Linux 使用 `/proc/self/fd`，缺失时 fail closed。ABA 回归证明攻击者 DB、WAL、SHM 保持未修改。
- `JsonlSessionStore` 构造失败路径确实会在未清空 `_root_fd` 时关闭，随后 `__del__` 可能关闭被 OS 复用的 descriptor。所有失败路径现统一调用先清空所有权的幂等 `close()`；回归测试在首次 close 内立即复用同一 fd，并证明 sentinel fd 仍然打开。
- fresh runner 原先在 store 构造成功后才注册 workspace。现在 workspace 创建后立即进入 `_RunResourceScope`，store 和 scheduler 分阶段绑定；store 构造失败测试证明 workspace 已关闭。
- runner、recovery 和 store close 链原先会被前一个 close 异常截断。现使用嵌套 `try/finally`，并在关闭前清空所有权；SQLite close 失败仍释放 DB/run-dir/audit fd，store close 失败仍关闭 workspace。
- workspace-free scheduler 原先依赖析构释放 artifact fd。`EvidenceMaterializer` 与 `DiscoveryScheduler` 现提供幂等 `close`/context-manager 生命周期，runner scope 确定性关闭 scheduler；standalone 回归证明 artifact fd 无泄漏且重复 close 安全。

### Fresh 验证结果

```text
pytest -q tests/equipment_deep_research/e2e/test_resume_run.py
29 passed in 0.76s

pytest -q tests/equipment_deep_research/integration/test_cli_workspace.py
40 passed in 0.22s

pytest -q tests/equipment_deep_research/integration/test_agent_harness.py
30 passed in 0.18s

pytest -q tests/equipment_deep_research/unit/test_store_savepoint.py
37 passed in 0.10s

pytest -q tests/equipment_deep_research/unit/test_secure_artifacts.py
2 passed in 0.01s

pytest -q tests/equipment_deep_research/e2e/test_resume_run.py \
  tests/equipment_deep_research/integration/test_cli_workspace.py \
  tests/equipment_deep_research/integration/test_agent_harness.py \
  tests/equipment_deep_research/unit/test_store_savepoint.py \
  tests/equipment_deep_research/unit/test_secure_artifacts.py
138 passed in 1.13s

pytest -q tests/equipment_deep_research/unit/test_secure_artifacts.py \
  tests/equipment_deep_research/unit/test_http_transport.py
29 passed in 0.05s

pytest -q tests/equipment_deep_research/integration/test_agent_harness.py \
  tests/equipment_deep_research/unit/test_agent_loop.py \
  tests/equipment_deep_research/unit/test_http_transport.py \
  tests/equipment_deep_research/unit/test_runtime_types.py
101 passed in 0.26s

pytest -q
253 passed in 1.61s

ruff check src/equipment_deep_research tests/equipment_deep_research
All checks passed!

python -m compileall -q src/equipment_deep_research tests/equipment_deep_research
exit 0

git diff --check
exit 0
```

全仓 `ruff check src tests` 仍报告 `knowledgegraph/demand_discovery` 下 6 个既有未使用 import；Task 5 scoped Ruff clean，本次未改动或回退这些其他所有者文件。

fresh CLI smoke 与同 run completed-resume smoke 均返回 `Status: completed`。恢复后 SQLite 为 `objects=14`、`trace=12`、`run_resumed=1`、稳定文件总数 `18`；E2E 的 completed-resume provider 断言保持 `0`，DB trace 与 `trace.jsonl` 一致。

## 最终复审后再修复

### Critical 1 技术结论与保证边界

Reviewer 对缺失 output-root 组件的判断成立：旧 `open_directory_handle(create=True)` 对缺失组件使用直接 `mkdirat` 后再 `lstat/openat`，公开组件名存在 mkdir-to-open 替换窗口。现已改为与 run/子目录相同的随机私有 staging：先以 128-bit 随机名创建、打开并记录 inode，再用 macOS `renameatx_np(RENAME_EXCL)` 或 Linux `renameat2(RENAME_NOREPLACE)` 发布。目标名被抢占时原子失败，不绑定或修改攻击者目录。create/open_existing 还要求最终 output root 由当前 effective UID 拥有，且不可 group/world writable；新建组件固定 `0700`。

Reviewer 关于“私有 staging 目录自身仍有 mkdir-to-open 窗口”的观察在恶意同 UID 进程模型下也成立，但要求完全消除此窗口超出 POSIX/macOS/Linux 现有目录 API 能力：`mkdirat(2)` 不返回新目录 fd，`openat(2)` 不能创建目录，macOS `renameatx_np` 与 Linux `renameat2` 只解决发布阶段，不能把目录创建和 handle 返回合并成一个 syscall。同 UID 进程还可读取同 UID namespace 并任意 rename/chmod；再加一次 pathname 检查只会移动 TOCTOU。除自定义 filesystem/VFS、特权 broker 或把攻击者隔离到不同 UID/mount namespace 外，不能诚实声称完全抵御持续枚举 staging 名的恶意同 UID 进程。

本任务实际保证的 invariant 是：

- 对预置目标、公开名称抢占、symlink/普通目录替换和测试 hook 所模拟的 rename race，published output/run/子目录要么是已绑定的创建 inode，要么 fail closed；绝不接受目标名中已有的攻击者普通目录。
- output root 是当前 UID 的私有非共享可写目录；随机 staging 名不作为公开接口，发布使用 no-replace 原语。
- 已发布后所有 Task 5 writer 从持有 fd 出发；output/run 名称后续被替换时只写原绑定 inode或 fail closed。
- 不声称抵御可持续枚举并操作同 UID 私有 namespace 的本机恶意进程；这是明确的 threat-model 边界，不以额外 stat 检查伪装成已解决。

新增回归覆盖缺失 output-root 组件抢占、run 名抢占、no-replace 原语缺失、shared-writable output root 拒绝，以及攻击者 marker/目录保持未修改。

### Critical 2 SQLite 无 sidecar 合同

WAL/SHM 的 pathname VFS 打开无法通过 Python 标准库预先绑定，因此删除该攻击面，而不是在写后审计：安全 workspace 模式在任何 schema 写前先用 `mode=rw` 打开，审计进程实际打开的主库 fd/inode，再设置 `PRAGMA journal_mode=MEMORY` 与 `PRAGMA synchronous=FULL`。`run.db-wal`/`run.db-shm` 不再创建。SQLite POSIX fd 复用场景只在没有出现新 regular-file descriptor、`PRAGMA database_list` 当前仍指向绑定 inode时接受；若 ABA 打开攻击者 inode，会观察到新错误 inode并在 schema 初始化前失败。

store 生命周期保留主库绑定 fd、SQLite audit fd 和 run-dir fd；每次 `_connect()` lease 前重新验证三者 identity 以及绑定目录中的 `run.db` 名称。leaf 被替换时后续 read/write 在 SQL 前失败，攻击者 DB 不变。fresh/output-root replacement、resume reconciliation replacement 与 leaf replacement 测试均证明攻击者 namespace 无 DB/sidecar 写入。

安全模式还会在 `sqlite3.connect` 前通过绑定 DB fd 检查 SQLite header 的 WAL read/write version，并通过绑定 run-dir fd拒绝遗留 `-wal`、`-shm`、`-journal`。旧 WAL 数据库不会在可变 pathname 上做隐式切换，而是要求离线可信迁移并 fail closed；回归证明拒绝发生前数据库 bytes 不变。

该模式保留 Phase 1 已测试的事务、异常注入、进程内 crash/resume 与 committed-savepoint 恢复合同；`MEMORY` journal 不提供 WAL 等价的掉电/进程被杀中途崩溃恢复保证，本报告不作该声明。若后续需要该等级 durability，需引入支持 fd/openat 的自定义 SQLite VFS 或把 SQLite 放入隔离 broker。

### Important 3 descriptor 生命周期

- `SqliteRunStore` 的全部 bound-fd acquisition 和 audit 已纳入统一异常清理；database dup、run-dir dup、类型/stat/path/audit/connect/initialize 任一失败都会先清空所有权并释放已取得 fd。
- 新增 `SqliteRunStore.for_workspace()`，runner/recovery 不再各自顺序取得两个 dup fd。factory 用 `ExitStack` 分阶段接管输入 handle；第 1/第 2 个 acquisition 失败和第 1/第 2 个 close 失败均保证其余 handle 继续关闭。若 input cleanup 在 store 构造成功后失败，已构造 store 也确定性关闭。
- 失败注入覆盖 constructor 的 database dup、directory dup、两 fd 后 audit，factory 的两个 acquisition 位置和两个 close 位置；caller 原 fd 保持有效，所有 partial-owned fd 均已关闭。

### 本轮 Fresh 结果

```text
pytest -q tests/equipment_deep_research/e2e/test_resume_run.py
29 passed in 0.77s

pytest -q tests/equipment_deep_research/integration/test_cli_workspace.py
44 passed in 0.18s

pytest -q tests/equipment_deep_research/integration/test_agent_harness.py
30 passed in 0.14s

pytest -q tests/equipment_deep_research/unit/test_store_savepoint.py
44 passed in 0.17s

pytest -q tests/equipment_deep_research/unit/test_secure_artifacts.py
2 passed in 0.02s

pytest -q tests/equipment_deep_research/e2e/test_resume_run.py \
  tests/equipment_deep_research/integration/test_cli_workspace.py \
  tests/equipment_deep_research/integration/test_agent_harness.py \
  tests/equipment_deep_research/unit/test_store_savepoint.py \
  tests/equipment_deep_research/unit/test_secure_artifacts.py
149 passed in 1.04s

pytest -q tests/equipment_deep_research/unit/test_secure_artifacts.py \
  tests/equipment_deep_research/unit/test_http_transport.py
29 passed in 0.11s

pytest -q tests/equipment_deep_research/integration/test_agent_harness.py \
  tests/equipment_deep_research/unit/test_agent_loop.py \
  tests/equipment_deep_research/unit/test_http_transport.py \
  tests/equipment_deep_research/unit/test_runtime_types.py
101 passed in 0.27s

pytest -q
264 passed in 1.67s

ruff check src/equipment_deep_research tests/equipment_deep_research
All checks passed!

python -m compileall -q src/equipment_deep_research tests/equipment_deep_research
exit 0

git diff --check
exit 0
```

安全扫描：`journal_mode=WAL` 在 Task 5 源码中无命中，测试中的唯一命中用于构造必须 fail closed 的 legacy-WAL 负向样本；`run.db-wal/shm` 仅命中“必须不存在”的断言；裸 `workspace.database_path.write_bytes` 仅命中 corrupt-DB 负向测试；`sessions_dir.resolve` 仅存在于 workspace-free Harness 兼容分支，runner/recovery 使用 handle 接口。`SqliteRunStore` 的 `dup_database_fd/dup_run_fd` 只存在于统一 factory。

fresh 与 completed-resume CLI smoke 均为 `Status: completed`。resume 后：`objects=14`、`trace=12`、`run_resumed=1`、`wal=False`、`shm=False`、`journal=False`、稳定文件总数 `16`；completed-resume provider E2E 保持 `0`。
