# 可插拔智能体 Provider

本项目参考 [OpenOPC](https://github.com/HKUDS/OpenOPC) 的外部 Agent 设计，将
Codex CLI、Claude Code 和国产智能体统一为 Provider。研究编排器只依赖统一的
`ModelMessage`、`ProviderStreamEvent`、结构化输出和 capability，不再依赖某个
CLI 的命令行细节。

## 已内置的 Provider

| Provider | 类型 | 协议 | 用途 |
|---|---|---|---|
| `codex` | `codex_cli` | Codex JSONL | 默认后端，保留隔离 `CODEX_HOME`、Schema 和审计 |
| `codex_deepseek` | `codex_cli` | Codex JSONL + Responses | DeepSeek 任务；官方直连、第三方自动桥接 |
| `codex_kimi` | `codex_cli` | Codex JSONL + Responses | Kimi 任务，与 GPT 的模型和运行目录隔离 |
| `responses` | `responses_http` | Responses SSE | API 兼容后端和搜索发现 |
| `deepseek` | `openai_compatible` | Chat Completions SSE | 仅保留给旧版非 Codex 调用 |
| `claude` | `external_cli` | Claude JSON | Claude Code 非交互执行 |
| `generic_cli` | `external_cli` | JSONL | 国产或第三方 CLI 配置模板 |
| `fake` | `fake` | 内存脚本 | 离线测试 |

## 选择 Provider

```bash
.venv/bin/python -m equipment_deep_research.interfaces.cli \
  --mode real \
  --provider claude \
  --topic "强干扰条件下的装备需求"
```

Codex CLI + DeepSeek（Codex CLI 是唯一执行链）：

```bash
export EQUIPMENT_DR_MODEL=deepseek-v4-flash
export EQUIPMENT_DR_DEEPSEEK_MODEL=deepseek-v4-flash
export EQUIPMENT_DR_DEEPSEEK_BASE_URL=https://api.deepseek.com/
export DEEPSEEK_API_KEY=...
./scripts/start-codex-deepseek.sh
```

`start-local.sh` 按 DeepSeek URL 主机自动选择执行路径：官方
`https://api.deepseek.com/` 直接使用原生 Responses API，不启动本地进程；其他主机
一律视为第三方 Chat Completions 中转站，启动 `responses_chat_bridge.py` 后再交给
Codex CLI。智谱 GLM Coding Plan
（`https://open.bigmodel.cn/api/v1`）与 Kimi K3（`https://api.moonshot.cn/v1`）
均由官方文档明确支持 `wire_api = "responses"`，因此不需要本地桥接。
桥接器只处理协议，不识别具体模型；上游 URL 可填写中转站根 `/v1` 地址或完整的
`/chat/completions` 地址。

Kimi K3 的官方 Codex 指南还注明其 Responses 端点不接受可选的
`search_context_size` 参数。切换到 Kimi 时在 env 中设置
`EQUIPMENT_DR_SEARCH_CONTEXT_SIZE_MODE=omit`；其他支持该字段的网关保持 `send`。

对于会把隐藏思考 token 计入 `max_tokens` 的推理模型，可在 env 中配置额外预算：

```dotenv
EQUIPMENT_DR_BRIDGE_THINKING=enabled
EQUIPMENT_DR_BRIDGE_REASONING_RESERVE_TOKENS=16384
EQUIPMENT_DR_BRIDGE_MAX_UPSTREAM_TOKENS=65536
```

桥接器会将 Codex 的可见输出预算与 reserve 相加；上游返回
`finish_reason=length` 时自动扩大请求体中的 `max_tokens` 并重试（最多三次），
避免结构化 JSON 因思考 token 被截断。上限和 reserve 都是通用配置，不含任何
DeepSeek 专有分支；不支持 `thinking` 字段的模型可设置
`EQUIPMENT_DR_BRIDGE_THINKING=disabled` 或留空。

S6 卡片的耗时阈值默认只用于观测，`EQUIPMENT_DR_S6_HARD_TIMEOUTS=0` 时不会因
单卡长耗时直接终止进程；失败卡片会生成受限卡片并继续汇总。只有部署明确需要
强制杀死超时进程时才将该变量设为 `1`。

Claude Code 需要在 Worker 环境中设置 `ANTHROPIC_API_KEY`。实际任务、Trace 和
API 响应只保存环境变量名，不保存密钥内容。

## 更换模型

模型 ID 完全属于部署配置，执行流不会根据模型名称分支。可以统一设置：

```bash
EQUIPMENT_DR_PROVIDER=claude
EQUIPMENT_DR_MODEL=claude-sonnet-4-20250514
```

也可以按 Provider 设置独立默认值（Provider 名称中的非字母数字字符会转换为
下划线并转为大写）：

```bash
EQUIPMENT_DR_CLAUDE_MODEL=claude-sonnet-4-20250514
EQUIPMENT_DR_RESPONSES_MODEL=qwen-plus
EQUIPMENT_DR_CODEX_MODEL=gpt-5.5
```

优先级为 Agent 环境覆盖、Provider 专用环境变量、全局
`EQUIPMENT_DR_MODEL`、`providers.yaml` 中的 profile 默认值。旧版 Agent 配置中
写入的 `provider: codex` 仅作为历史默认值；切换 `EQUIPMENT_DR_PROVIDER` 后会
自动跟随当前 Provider，只有在 `EQUIPMENT_DR_AGENT_MODELS_JSON` 中显式指定时
才固定某个 Agent 的 Provider。

所有 Provider 都支持同一套端点别名，不需要修改 YAML：

```bash
EQUIPMENT_DR_DEEPSEEK_MODEL=deepseek-reasoner
EQUIPMENT_DR_DEEPSEEK_BASE_URL=https://api.deepseek.com/v1/chat/completions
EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV=DEEPSEEK_API_KEY
```

Agent 也可用简单变量覆盖（变量名中的短横线会转换为下划线）：

```bash
EQUIPMENT_DR_AGENT_REPORTER_PROVIDER=deepseek
EQUIPMENT_DR_AGENT_REPORTER_MODEL=deepseek-reasoner
```

## 配置一个国产 CLI

在 `configs/equipment_deep_research/providers.yaml` 增加一个 `external_cli`：

```yaml
providers:
  qwen_code:
    type: external_cli
    label: 通义代码智能体
    command: qwen
    protocol: jsonl
    model: qwen-max
    model_flag: --model
    schema_flag: --output-schema
    schema_mode: file
    api_key_env: EQUIPMENT_DR_QWEN_API_KEY
    api_key_target_env: DASHSCOPE_API_KEY
    base_url_env: EQUIPMENT_DR_QWEN_BASE_URL
    base_url_target_env: DASHSCOPE_BASE_URL
    base_args: []
    extra_args: []
    timeout_seconds: 900
    retry_attempts: 1
```

该 CLI 只需要满足：从 stdin 接收完整 Prompt、按 JSON/JSONL 输出最终结果，且
结果中包含 `result`、`text`、`output` 或 `structured_output` 之一。若命令格式、
会话协议或错误码特殊，再实现一个独立 Python 插件并注册到 Provider Registry，
不需要修改编排器。

## Provider 能力

Provider 通过 `ProviderCapabilities` 声明：

- `structured_output`：是否支持严格结构化结果
- `isolated_sessions`：是否支持 Agent/动态子 Agent 隔离
- `cancellation`：是否可终止子进程
- `workspace_scope`：是否在受控工作目录运行
- `hosted_web_search`：是否提供托管搜索

业务代码按 capability 路由；Provider ID 只用于配置、展示和审计。

## fallback

可在 Provider 配置中声明备用链：

```yaml
providers:
  claude:
    type: external_cli
    fallback_providers: [codex]
```

备用链只在首个 Provider 尚未产生最终事件且启动、超时、限流或网络类错误时
切换。结构化结果错误、权限错误和业务契约错误不会静默切换，避免同一任务在
不同模型间产生不可追溯的语义漂移。

## 复杂 Provider 的扩展边界

当前版本优先采用受控 YAML 配置，避免 Worker 动态加载不受信任代码。对于需要
自定义网关、会话恢复或特殊流式协议的 Provider，建议下一步以独立 Python 包
实现同一 `ModelProvider`/`ProviderCapabilities` 契约，再由部署镜像显式安装并
注册。插件负责命令构造、输出解析、能力声明和配置校验；本地 Harness 仍负责
工具、证据、权限、保存点和报告质量门控。
