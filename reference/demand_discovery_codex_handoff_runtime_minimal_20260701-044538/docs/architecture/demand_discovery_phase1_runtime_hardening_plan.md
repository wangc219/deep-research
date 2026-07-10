# Demand Discovery Phase 1: Runtime Hardening Implementation Plan

日期：2026-06-11

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**定位：** 本文是 `demand_discovery_long_run_evolution_plan.md` Phase 1 的细粒度实施计划，对应里程碑门禁 M-LR1。

**Goal:** 让 harness 内核具备长时运行的四项基础能力：全链路取消与超时、崩溃可恢复、预算与收尾协议、研究记忆 compaction。

**Architecture:** 不改变既有两层边界（无状态 `AgentLoop` + 有状态 `DiscoveryHarness`）与四通道工具契约。所有新能力以"边界检查点 + append-only 持久化"方式接入，不引入后台线程、不引入全局状态。

**Tech Stack:** Python standard library only（`asyncio`、`dataclasses`、`json`、`time.monotonic`）。本阶段不新增第三方依赖。测试全部离线。

**参考实现总表：**

| 参考 | 借鉴点 | 对应 Task |
|---|---|---|
| `reference/pi/packages/agent/src/agent-loop.ts` | AbortSignal 在 provider 请求前/工具执行前的协作式检查点位置；abort 后补齐完整事件序列而非半截流 | P1.1 |
| anyio `CancelScope` / Python 3.11 `asyncio.timeout` | 结构化取消语义：deadline 派生、父子传播；用 `asyncio.wait_for` 实现 per-tool 硬超时 | P1.1 |
| `reference/pi/packages/agent/src/harness/session/jsonl-storage.ts` + `docs/durable-harness.md` | 重放式恢复：JSONL 逐行重放还原状态；leaf-affecting entry 决定恢复点 | P1.2 |
| LangGraph checkpointer（`langchain-ai/langgraph`，`BaseCheckpointSaver`/`SqliteSaver`） | "在 super-step 边界写 checkpoint、按 thread_id 恢复"的持久化粒度——对应本项目的 save point 边界 | P1.2 |
| OpenAI Agents SDK（`openai/openai-agents-python`，`Runner.run(max_turns=)` 与 `MaxTurnsExceeded`） | 轮数/预算护栏放在 run 循环边界、超限产生显式可捕获结果而非静默截断 | P1.3 |
| Anthropic 多 agent 研究系统工程博客（2025-06） | 给每个 agent 显式 effort/token 预算、预算尽时收尾输出而非丢弃已得发现 | P1.3 |
| `reference/pi/packages/agent/src/harness/compaction/compaction.ts` | `shouldCompact` 阈值、`findCutPoint` 避开 tool result 切点、split-turn 标记、摘要 entry 只改未来投影不删历史 | P1.4 |
| OpenHands `LLMSummarizingCondenser`（`All-Hands-AI/OpenHands`） | "保留头部 + 摘要中段 + 保留近期"的 condenser 形态；摘要失败可跳过下轮重试 | P1.4 |
| Manus context engineering 博客（2025-07） | append-only 上下文（KV-cache 友好）；大内容外置文件系统、上下文只留引用——印证既有 artifact/摘录设计，compaction 不破坏前缀稳定性 | P1.2 / P1.4 |

---

## 1. Scope

| Task | 交付物 | 依赖 |
|---|---|---|
| P1.1 | `CancelToken` 全链路 + per-tool 超时 + `abort()` 真中断 | 无 |
| P1.2 | message 级持久化时序 + `from_session()` 恢复 + DomainStore 增量持久化 | P1.1（aborted entry） |
| P1.3 | `RunBudget` + 收尾协议 + usage 计费管道 | 无（与 P1.2 可并行） |
| P1.4 | compaction 算法 + 研究记忆摘要 + 上下文投影 | P1.2（compaction entry 持久化）、P1.3（compaction 计费） |
| P1.5 | SSE 真流式（可顺延并入 Phase 3 P3.5） | 无 |

完成判定（M-LR1）：长任务运行中 abort 1 秒内停止且无半截写入；kill 进程后 `from_session()` 续跑通过测试；预算超额触发收尾协议；上下文超阈值自动 compaction 且摘要进入下次请求。

---

## 2. Task P1.1: CancelToken 全链路与超时

**Files:**

- Create: `src/knowledgegraph/demand_discovery/harness/cancellation.py`
- Modify: `src/knowledgegraph/demand_discovery/harness/agent_loop.py`
- Modify: `src/knowledgegraph/demand_discovery/harness/agent_harness.py`
- Modify: `src/knowledgegraph/demand_discovery/harness/tools.py`
- Modify: `src/knowledgegraph/demand_discovery/llm/responses_adapter.py`
- Test: `tests/test_demand_discovery_cancellation.py`

### 设计要点

协作式取消（不用 `task.cancel()` 强杀），保证 save point 不变式不被破坏；硬超时只作用于单个工具执行。

```python
class RunCancelled(RuntimeError):
    """Raised at a cooperative checkpoint after the token is cancelled."""

class CancelToken:
    def __init__(self, parent: "CancelToken | None" = None,
                 timeout_ms: int | None = None) -> None: ...
    def cancel(self, reason: str = "") -> None: ...
    @property
    def cancelled(self) -> bool: ...   # 自身 cancel / parent.cancelled / 超过 deadline
    @property
    def reason(self) -> str: ...       # "user_abort" | "timeout" | ...
    def raise_if_cancelled(self) -> None: ...
    def derive(self, timeout_ms: int | None = None) -> "CancelToken": ...
```

- deadline 用 `time.monotonic()` 在构造时计算，`cancelled` 属性惰性判断——无后台 timer、无任务句柄。
- 父子传播单向：父 cancel 时所有派生 token 同时 cancelled（Phase 2 的 worker token 派生依赖此语义）。

**检查点位置**（对齐 Pi agent-loop 的 signal 检查位）：

1. `AgentLoop._run` while 循环顶部（`prepare_next_turn` 之前）。
2. `_stream_assistant` 发起 provider 请求前，以及消费 provider event 的 `async for` 循环体内（每个事件检查一次，取消则停止消费并抛 `RunCancelled`；in-flight HTTP 允许自然结束后丢弃结果）。
3. `_execute_tool_calls` 每个工具启动前。

**per-tool 硬超时：** `ToolDefinition` 增加 `timeout_ms: int = 60_000`；`ToolRegistry.execute()` 用 `asyncio.wait_for` 包裹，`TimeoutError` 归一为 error `ToolResult`（loop 继续，不终止 run）——超时是工具级故障，取消是 run 级终止，二者语义分离。

**RunCancelled 的事件收敛：** loop 捕获 `RunCancelled` 后补齐事件序列（若 turn 未闭合则发 `turn_end {"aborted": true}`），发 `agent_end {"aborted": true}`，`stream.end(state.messages)` 正常结束——不走 `stream.error`，调用方拿到的是完整但被截停的 run（对齐 Pi"abort 不产生半截流"的行为）。

**harness 接线：**

- `DiscoveryHarness.__init__` 创建 run 级 `CancelToken`；`prompt()` 每次启动时若 token 已 cancelled 则换新 token。
- `abort()` 升级：保持既有队列语义（清 steer/follow-up、保留 next_turn）不变，新增 `self._cancel_token.cancel("user_abort")`。
- abort 收敛路径：loop 结束后 harness 检测 aborted 标记 → **丢弃** `_pending_domain` / `_pending_trace`（不 flush；半截 turn 的 proposal 不可信）→ 写 session entry `aborted {"dropped_domain": n, "dropped_trace": m}` → `settled {"aborted": true}` → phase 回 `idle`。
- `ToolExecutionContext` 增加 `cancel_token` 字段，工具实现（Phase 3 网络工具）可在长 IO 内部自查。

### Steps

- [ ] **Step 1: 写失败测试**，覆盖：
  - token 基本语义：cancel 传播到派生 token；timeout_ms 到期自动 cancelled；`raise_if_cancelled` 抛 `RunCancelled`。
  - abort 时序：fake provider 注入一个 `asyncio.sleep(5)` 的慢工具，run 启动后 0.1s 调 `abort()`，断言 1s 内 `settled` 事件到达、`payload["aborted"] is True`。
  - 无半截写入：慢工具前一轮已产生 proposal 并 flush，慢工具本轮 proposal 被丢弃——断言 store 内容与上一 save point 一致、`aborted` entry 记录了丢弃数。
  - per-tool 超时：`timeout_ms=50` 的工具产生 error ToolResult，loop 继续执行后续轮次。
  - abort 后 phase 回 idle、next_turn 队列保留、再次 `prompt()` 可正常启动。

```python
async def test_abort_mid_turn_drops_pending_proposals(self):
    provider, harness, store = make_harness_with_slow_tool(sleep_s=5.0)
    task = asyncio.create_task(harness.prompt("start"))
    await asyncio.sleep(0.1)
    harness.abort()
    await asyncio.wait_for(task, timeout=1.0)
    self.assertEqual(harness.phase, "idle")
    self.assertEqual(store.snapshot_ids(), store_ids_at_last_save_point)
```

- [ ] **Step 2: 实现 `cancellation.py` 并接线 loop / tools / provider。**
- [ ] **Step 3: 升级 `abort()` 与收敛路径**；既有 86 测试不得回归（abort 旧测试只断言队列语义，应仍通过）。
- [ ] **Step 4: Run** `python -m unittest tests.test_demand_discovery_cancellation tests.test_demand_discovery_agent_harness tests.test_demand_discovery_agent_loop -v` → PASS。

---

## 3. Task P1.2: 持久化时序对齐与 session resume

**Files:**

- Modify: `src/knowledgegraph/demand_discovery/harness/agent_loop.py`（message_appended 事件）
- Modify: `src/knowledgegraph/demand_discovery/harness/agent_harness.py`
- Modify: `src/knowledgegraph/demand_discovery/harness/session_store.py`
- Modify: `src/knowledgegraph/demand_discovery/domain/store.py`
- Modify: `src/knowledgegraph/demand_discovery/harness/trace_store.py`
- Test: `tests/test_demand_discovery_session_resume.py`

### 设计要点

**持久化时序对齐 Pi**（消除现状 `agent_harness.py:218-221` 的"run 结束后批量写"）：

- loop 每次向 `state.messages` 追加消息（assistant 最终消息、tool result 批、steering 注入）后发新事件 `message_appended {"message": <dict>}`，按追加顺序逐条发。
- harness 在 `_handle_loop_event` 收到 `message_appended` 时立即写 session（替换现 prompt() 尾部的批量回写）；`turn_end` 时 flush proposal 并写 `save_point` entry（现有行为）；run 正常结束写 `settled` entry。
- 崩溃最坏丢失：当前未到 save point 的 turn。这是与 LangGraph "checkpoint per super-step" 相同的粒度选择——save point 即本项目的 super-step 边界。

**队列持久化：** `next_turn()` 入队与 prompt() 消费时各写一条 `queue_update` entry（`{"queue": "next_turn", "op": "push"|"drain", ...}`）。steer/follow-up 不持久化（运行中瞬态，崩溃后注入语境已失效，文档化该取舍）。

**恢复构造：**

```python
@classmethod
def from_session(cls, session_path: Path, *, provider, tools,
                 domain_store, trace_store=None, context_builder=None,
                 run_id: str | None = None) -> "DiscoveryHarness":
```

重放规则：

1. 逐行读 entries；`message` entry 重建 `_messages`；`active_tools` entry 重建 `_active_tool_names`；`queue_update` 重建 next_turn 队列（push 累积、drain 清空）；`compaction` entry 重建投影状态（P1.4 落地后生效）。
2. 找最后一个 `save_point` 或 `settled` entry 作为恢复点；其后的 `message` entries 属于半截 turn，整体丢弃，并追加一条 `recovered_from_crash {"dropped_entries": n, "after_entry_id": ...}`。
3. run_id 沿用 session header（`__init__` 同步增加 `run_id` 参数，替换写死的 `"harness"`，`JsonlSessionStore` header 记录 run_id）。

**领域层增量持久化（事件溯源式，append-only）：**

```python
class DomainStore:
    def bind_jsonl(self, path: Path) -> None: ...
    # save point flush 成功后逐条追加已接受的 proposal：
    #   {"kind": "domain", "action": ..., "object_type": ..., "payload": {...}}
    @classmethod
    def load_jsonl(cls, path: Path) -> "DomainStore": ...
    # 逐行经 apply_domain_proposal 重放（upsert 幂等）
```

`DomainTraceStore` 同样增加可选 JSONL 绑定（本就是 append-only 事件日志，直接逐条落盘）。替换现 demo 的"结束时 export_jsonl 全量导出"为增量绑定；`export_jsonl` 保留作快照导出。

### Steps

- [ ] **Step 1: 写失败测试**，覆盖：
  - turn 中途断言：慢工具执行期间（用事件钩子同步）JSONL 已含本轮 user message 与上一轮 assistant message。
  - 崩溃恢复：构造一个写到一半的 session 文件（含 save_point 后的孤儿 message entries），`from_session()` 后孤儿被丢弃、`recovered_from_crash` entry 存在、`_messages` 与恢复点一致。
  - next_turn carry 跨恢复：crash 前 `next_turn("x")`，恢复后第一次 prompt 不注入、第二次注入（双桶语义保持）。
  - DomainStore 往返：bind_jsonl 增量写入后 `load_jsonl` 重建的 store 与原 store `to_run_state()` 相等。
  - 恢复后续跑：恢复的 harness 继续 prompt，新 trace 事件 run_id 与原 run 一致。
- [ ] **Step 2: 实现 `message_appended` 事件与 harness 即时落盘**（删除批量回写路径）。
- [ ] **Step 3: 实现 `from_session()`、`queue_update` 持久化、`bind_jsonl`/`load_jsonl`。**
- [ ] **Step 4: Run** 全量 demand discovery 测试 → PASS。`demo.py` 改用 bind_jsonl，`scripts/demand_discovery_demo.py --mode fake` 输出不变。

---

## 4. Task P1.3: RunBudget 与收尾协议

**Files:**

- Create: `src/knowledgegraph/demand_discovery/harness/budget.py`
- Modify: `src/knowledgegraph/demand_discovery/harness/agent_loop.py`（usage 透传）
- Modify: `src/knowledgegraph/demand_discovery/harness/agent_harness.py`
- Modify: `src/knowledgegraph/demand_discovery/llm/fake_provider.py`（usage 估算）
- Modify: `src/knowledgegraph/demand_discovery/workers/prompts.py`（收尾 prompt）
- Test: `tests/test_demand_discovery_budget.py`

### 设计要点

```python
@dataclass
class RunBudget:
    max_tokens: int | None = None
    max_tool_calls: int | None = None
    max_wall_clock_ms: int | None = None
    spent_tokens: int = 0
    spent_tool_calls: int = 0
    started_at_monotonic: float = 0.0
    def charge_usage(self, usage: dict) -> None: ...   # input+output；cached 减半计或不计，常数置于模块顶
    def charge_tool_call(self) -> None: ...
    def exhausted(self) -> str | None: ...             # 首个触发维度名 / None
    def remaining_summary(self) -> dict: ...           # 进度展示用
```

**计费点：** `AssistantMessage.usage` 字段已存在（`llm/types.py:46`）。loop 在 `message_end` 后把 usage 通过事件 payload 上报（`message_end` payload 增加 `usage`）；harness 订阅计费。tool call 在 `tool_execution_end` 计数。fake provider 补 usage 估算（`ceil(chars/4)`），使预算测试可离线确定。

**检查点与收尾协议（graceful wrap-up）：** 检查只发生在 `_prepare_next_turn` 边界（下一次 provider 请求前），不在 turn 中途硬断——保证 save point 完整性。借鉴 OpenAI Agents SDK 的 `max_turns` 边界语义与 Anthropic 多 agent 系统"预算尽时输出已得发现"的原则：

```text
exhausted 且未在收尾态:
  注入收尾消息（prompts.WRAP_UP_PROMPT：把已确认发现写入领域对象、
  列出未解问题与下一步检索方向、停止发起新检索/新阅读）
  wrap_turns_left = 2；发 RuntimeEvent budget_exhausted {"dimension": ...}
收尾态:
  每次 prepare 递减 wrap_turns_left；归零 → state.stop = True
```

`max_turns` 保留为后备护栏并提高默认值至 64；真实约束由 RunBudget 承担。`DiscoveryHarness.__init__` 增加 `budget: RunBudget | None` 参数。

**收尾态硬约束：** 收尾消息只是给模型解释当前状态，不能作为唯一控制手段。harness 在进入 wrap-up 状态后向 `ToolExecutionContext` 暴露 `budget_state="wrapping_up"`，`before_tool_call` 默认策略阻断会扩大成本或开新分支的工具，例如 `spawn_worker`、`search_sources`、`fetch_page`、`read_document` 的新文档读取；仍允许写入已得发现、生成审核/报告、读取已引用证据等收尾工具。阻断返回 error `ToolResult`，content 固定提示"预算已进入收尾态，只能整理既有发现"，并发 `budget_tool_blocked` RuntimeEvent。这样即使模型忽略 prompt，也无法继续放大调研范围。

### Steps

- [ ] **Step 1: 写失败测试**：token 预算耗尽 → 收尾消息出现在下次 provider 请求的 messages 中、run 未立刻终止；两轮后强制停止；`max_tool_calls` 独立触发；`budget_exhausted` 事件可观测且 payload 含维度名；wrap-up 状态下 `spawn_worker`/`search_sources`/`fetch_page` 被程序阻断并发 `budget_tool_blocked`；无预算时行为与现状完全一致（回归保护）。
- [ ] **Step 2: 实现 `RunBudget`、usage 透传、harness 接线与收尾协议。**
- [ ] **Step 3: Run** `python -m unittest tests.test_demand_discovery_budget -v` 与全量测试 → PASS。

---

## 5. Task P1.4: 研究记忆 compaction

**Files:**

- Create: `src/knowledgegraph/demand_discovery/harness/compaction.py`
- Modify: `src/knowledgegraph/demand_discovery/harness/agent_harness.py`
- Modify: `src/knowledgegraph/demand_discovery/workers/prompts.py`
- Test: `tests/test_demand_discovery_compaction.py`

### 设计要点

**算法骨架直接翻译 Pi `compaction.ts`：**

```python
@dataclass
class CompactionSettings:
    context_window: int = 128_000
    reserve_tokens: int = 16_384      # Pi 默认值
    keep_recent_tokens: int = 20_000  # Pi 默认值

def should_compact(context_tokens: int, s: CompactionSettings) -> bool:
    return context_tokens > s.context_window - s.reserve_tokens

def find_cut_point(messages: list[AgentMessage], keep_recent_tokens: int) -> int:
    # 从尾部向前累计估算 token；达到阈值后取切点：
    # - 切点消息不得是 tool_result（上下文不能以孤儿工具结果开头）
    # - 优先回退到最近的 user message 边界（完整 turn）
    # - 回退超过 SPLIT_TURN_LOOKBACK 条仍找不到则就地切并标记 split_turn
```

token 估算复用 `ContextPackBuilder._estimate_tokens`（ceil(len/4)）；有 provider usage 时（P1.3 已透传）优先用最近一次请求的真实 context tokens 判断阈值（对齐 Pi `estimateContextTokens` 的"usage 优先"策略）。

**摘要 = LLM 自由文本 + 程序生成的结构化索引段。** 关键防丢失设计：LLM 按研究记忆模板生成叙述摘要（当前需求假设、关键证据 claim 一句话、反证与限制、已排除方向、未解问题、下一步方向——模板进 `prompts.COMPACTION_PROMPT`）；随后**程序**从 `DomainStore` 机械生成索引段（evidence/candidate id 与状态清单）拼接其后。id 不经过模型之手，无丢失风险，也无需对摘要做校验回环（借鉴 OpenHands condenser 的"摘要可不完美、关键状态另持久化"思路——本项目领域状态本就在 store，摘要只服务上下文）。

**执行与投影：**

- save point 内检查 `should_compact`；触发时 phase 进入 `compaction`（枚举已预留），用当前 provider 发一次摘要请求（计入预算），产出 `compaction` session entry：`{"summary": str, "cut_index": int, "split_turn": bool}`。
- harness 维护 `_compaction` 最新记录；新增 `_project_messages()`：无 compaction 时返回 `_messages` 原样，有则返回 `[summary_as_user_message] + _messages[cut_index:]`。loop 启动与 `prepare_next_turn` 改用投影结果。**原始 `_messages` 与 session entries 不删不改**（append-only 不变式；亦符合 Manus"上下文前缀稳定"原则——压缩只发生在 save point 边界，轮内前缀不变）。
- compaction 请求失败：记 RuntimeEvent `compaction_failed`，本轮跳过，下个 save point 重试（不致命）。
- `from_session()` 重放 `compaction` entry 恢复投影状态（P1.2 已留位）。
- compaction 期间 `prompt()` 拒绝启动（phase 校验已有）。

### Steps

- [ ] **Step 1: 写失败测试**：
  - 阈值：超限触发、未超限不触发（settings 注入小窗口便于测试）。
  - cut point：切点不落 tool_result；优先 user 边界；构造无 user 边界场景验证 split_turn 标记。
  - 投影：compaction 后下一次 provider 请求收到 `[摘要消息, ...近期消息]`（fake provider 记录收到的 context 断言）；原始 entries 仍全量在 session。
  - 索引段：摘要尾部含 store 中全部 evidence/candidate id（fake provider 返回固定摘要文本，索引段由程序拼接，断言其存在性与完整性）。
  - 失败容忍：摘要请求报错 → run 继续、`compaction_failed` 事件、下个 save point 重试。
  - 恢复：含 compaction entry 的 session 经 `from_session()` 后投影立即生效。
- [ ] **Step 2: 实现算法函数（纯函数优先，便于独立测试）。**
- [ ] **Step 3: harness 接线（phase 流转、投影、持久化、预算计费）。**
- [ ] **Step 4: Run** 全量测试 → PASS。

---

## 6. Task P1.5: SSE 真流式（可顺延）

**Files:**

- Modify: `src/knowledgegraph/demand_discovery/llm/responses_adapter.py`
- Test: `tests/test_demand_discovery_responses_adapter.py`（追加）

### 设计要点

现状 `responses_adapter.py:87` `list(self._transport(...))` 先收完整响应再解析。改造：transport 契约不变（返回行迭代器），`_run` 不再物化列表，而是在工作线程逐行读取、经 `loop.call_soon_threadsafe` 推入 `asyncio.Queue`，async 侧逐行喂 `parse_sse_lines` 的增量版本并即时 `stream.push`；`response.completed` 事件后立即收敛（即使 body 未关闭）。重试语义只覆盖"首字节前失败"；已开始产出 delta 后失败则直接 error（避免重复内容）。

本任务允许整体顺延并入 Phase 3 P3.5（真 provider 冒烟时一并验证），不阻塞 P1 验收。

- [ ] 追加断言：transport 产出第一行后，消费方即可收到第一个 `text_delta`（用线程事件同步验证，无 sleep 竞态）。

---

## 7. 验收门禁（M-LR1）

- [ ] `python -m unittest discover -s tests -p "test_demand_discovery_*.py" -v` 全量 PASS（含新增 4 个测试模块）。
- [ ] `python scripts/demand_discovery_demo.py --mode fake` 行为不变（输出含 candidate/evidence/audit/report/trace 计数，无密钥泄漏）。
- [ ] kill-and-resume 演练：运行 fake demo 变体（慢工具拉长 run）→ 进程 kill → `from_session()` 续跑成功；演练脚本与 session 文件前后对照存入 `outputs/runs/` 并在 commit message 注明。
- [ ] 既有 86 测试零回归。

## 8. Self-Review

- 取消采用协作式而非 `task.cancel()`：牺牲极端场景的即时性（最长等一个工具超时周期），换取 save point 不变式无条件成立。per-tool `wait_for` 已覆盖最常见的卡死源（网络 IO）。
- steer/follow-up 不持久化是有意取舍：崩溃后其注入语境已失效，恢复反而引入误导输入。
- 摘要索引段由程序生成而非校验模型输出，是本阶段最重要的防御性设计；领域状态真值始终在 DomainStore，compaction 只影响模型视图。
- 本阶段全部 stdlib 实现，无新依赖；P1.5 是唯一允许顺延项。
