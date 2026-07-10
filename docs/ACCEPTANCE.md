# 验收说明

## 项目要求对应

- 三条研究路线均可运行：
  - 新制胜机理路线。
  - 传统能力缺口路线。
  - 局部战争案例路线。
- 架构图主流程已落地：
  - 分析师输入。
  - 编排器问题解析。
  - 动态基线 agent 池并发研判。
  - 编排器汇总 coverage。
  - 制胜机理 L1/L2/L3。
  - 缺失能力触发再调请求，并写入 summary 与 trace。
  - 五判据审计。
  - 能力画像报告输出。
- 默认四 agent 不写死：
  - 支持默认全量运行。
  - 支持 `--agents` 只运行子集。
  - 缺失 capability 会写入报告限制，不伪造全覆盖。

## 参考项目吸收

- Pi：
  - 小内核、大 harness。
  - 独立 session。
  - save point 和 trace。
- Nanobot：
  - registry 分层。
  - config/workspace 分离。
- GenericAgent：
  - 上下文信息密度优先。
  - 子任务隔离。
  - checkpoint 和 handoff summary。

## 必验命令

```bash
python3 -m pytest
python3 scripts/run_deep_research.py --mode fake --topic "低空无人机探测预警能力缺口" --research-route auto --run-id fake-full
python3 scripts/run_deep_research.py --mode fake --topic "低空无人机探测预警能力缺口" --agents combat_scenario,weapon_equipment --run-id fake-subset
python3 scripts/run_deep_research.py --mode real --topic "低空无人机探测预警能力缺口" --research-route auto --run-id real-smoke
```

说明：如果运行环境无法访问公网，`real-smoke` 不应伪造联网成功；系统会写入 `artifacts/` 诊断文件，并将审计状态降级为 `limited`。在公网可用环境下，至少应出现一个 `source_materials.status=fetched`。

公开来源必须经过质量过滤：

- 搜索结果只有完成抓取、正文定位和质量评分后才能形成正式 `EvidenceCard`。
- 未达到质量阈值的材料保留为 candidate/rejected，不进入 `BaselineFindingPacket.evidence_ids`。
- 冲突和反证材料必须保留状态与原因，不能静默删除。
- 网络安全由 URL/SSRF、响应大小、重定向、超时和限速策略强制执行。

## 必验产物

每个 run 目录至少包含：

- `report.md`
- `capability_images.json`
- `round_summary.json`
- `domain.jsonl`
- `trace.jsonl`
- `agent_sessions/`
- `artifacts/`

## 不包含项

正式源码不包含旧演示执行链路入口。

## 企业级前后端验收扩展

- Web、CLI 和 API 使用同一领域对象和研究内核。
- 分析师可通过 Web 创建、启动、暂停、恢复、取消、审阅和导出研究任务。
- reviewer 未确认时不能发布 approved 报告。
- SSE 断线重连和浏览器刷新不影响后台长任务。
- analyst、reviewer、auditor、admin 权限由 API 服务端强制执行。
- Docker Compose 可启动 Web、API、worker、PostgreSQL、Redis 和反向代理，并通过健康检查。
