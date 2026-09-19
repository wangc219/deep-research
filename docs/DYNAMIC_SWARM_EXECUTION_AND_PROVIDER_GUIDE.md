# 动态蜂群执行流与模型接入契约

动态蜂群的生产链路固定为：

1. `create_run` 写入任务、执行配置和幂等事件；Worker 以 `queued → planning` 抢占任务。
2. Orchestrator 生成研究蓝图、依赖波次和动态 MissionGraph；每个 specialist 只回传 typed packet。
3. Scheduler 按依赖就绪并发执行，`AdaptiveCallGate` 负责全局限流、优先级保留和失败降速。
4. Candidate ledger 持久化每次招募、合并、淘汰和回溯；恢复从最近 ledger/checkpoint 继续，不重复已完成调用。
5. S5/S6 汇聚候选与证据，Audit/QualityGate 检查引用、结构、硬约束和交付完整性。
6. Reporter 生成报告，进行结构化修复、硬上限裁剪、审计和 DeliveryExporter 发布；失败可从 delivery checkpoint 单独恢复。

GPT 与 DeepSeek 都通过 `ModelProvider` 统一接口接入：`stream(messages, tools, options)` 输出标准化事件，能力由 `ProviderCapabilities` 声明。当前实现分别是 Codex/Responses 适配器和 OpenAI-compatible Chat Completions 适配器。新增模型只需：

- 增加一个 provider profile（配置 `type`、endpoint、credential env、model）；
- 实现 `ModelProvider`，把厂商流式响应转换成 `ProviderStreamEvent`；
- 在 `ProviderRegistry` 注册构造逻辑，复用现有工具、重试、限流、checkpoint、质量门禁。

编排层不应判断厂商名称；只应读取 `capabilities()`，例如是否支持工具、结构化输出、隔离会话和 hosted search。全局 `EQUIPMENT_DR_MODEL` 是蜂群模型的统一路由，只有显式 `EQUIPMENT_DR_AGENT_MODELS_JSON` 才覆盖单个 agent。
