# 需求挖掘 Query Library

Query Library 保持独立的数据、服务和 Worker 边界，同时已挂载到现有主 API 与研究工作台。它负责人工维护、联网生成、审核和保存可直接提交研究系统的完整 Query；已发布 Query 可在前端一键带入 Deep Research 任务，并在任务执行快照中记录 Query ID 与版本。

## 数据与运行方式

- 默认数据库：`outputs/query-library.db`
- 自定义数据库：设置 `EQUIPMENT_DR_QUERY_LIBRARY_DB`，或向 CLI 传入 `--database-url`
- 主工作台 API：`/api/v1/query-library`；仍可用独立 `serve` 命令运行在单独端口
- 自动生成使用现有 `configs/equipment_deep_research/providers.yaml` 和对应服务端凭据
- 人工新增、编辑、发布、归档和种子导入不需要模型凭据或网络

主 API 和 `start-local.sh` 会幂等导入初始材料，也可手工执行：

```bash
PYTHONPATH=src python3 -m equipment_deep_research.query_library import-seeds
```

独立启动 API 和生成 Worker：

```bash
PYTHONPATH=src python3 -m equipment_deep_research.query_library serve --port 8010
PYTHONPATH=src python3 -m equipment_deep_research.query_library worker
```

直接从 CLI 生成并等待完成：

```bash
PYTHONPATH=src python3 -m equipment_deep_research.query_library generate \
  --topic "无人远程火力打击装备" \
  --supplemental-information "面向未来高端战争，兼顾体系化、智能化和规模化"
```

人工维护示例：

```bash
PYTHONPATH=src python3 -m equipment_deep_research.query_library add \
  --query "研究低空无人火力装备的体系能力需求" \
  --generation-rationale "由人工根据低空作战痛点提出"

PYTHONPATH=src python3 -m equipment_deep_research.query_library list --status draft
PYTHONPATH=src python3 -m equipment_deep_research.query_library publish QUERY_ID --version 1
```

## API

所有接口使用 `/api/v1/query-library` 前缀：

- `POST /generations`：提交异步联网生成任务
- `GET /generations/{generation_id}`：查询任务状态、来源和结果 Query ID
- `POST /generations/{generation_id}/retry`：重试失败任务
- `GET /queries`、`GET /queries/{query_id}`：检索 Query 与修订历史
- `POST /queries`、`PATCH /queries/{query_id}`：人工新增和编辑
- `POST /queries/{query_id}/publish`、`POST /queries/{query_id}/archive`
- `POST /queries/bulk-status`：批量状态变更

自动生成分为轻量联网校验与结构化 Query 生成两阶段。生成来源只是选题形成线索，不替代后续 Deep Research 的正式证据采集和核验。生成任务成功时整批原子写入草稿；质量门控不满足目标数量时整批失败，不保存部分结果。

## 前端交互

- 研究任务首页提供 Deep Research Query 输入框和推荐 Query，用户可直接输入，也可点击推荐项自动回填后进入任务配置。
- 首页“需求研究问题库”卡片打开独立需求挖掘界面，可输入主题并提交 12 条 Query 的异步生成任务；该界面提供“返回研究任务”入口。
- Query 卡片展示状态、来源类型、生成理由和来源数量；详情区可查看研究角度与来源关联说明。
- Agent 生成和资料导入内容默认是草稿，可“审核发布”或“发布并新建研究”。
- 已发布 Query 可一键回填研究任务的问题和补充信息，创建时后端再次校验状态与版本。
- 研究任务运行记录采用卡片式任务中心，展示状态、信源、证据、能力候选、报告和实时执行位置。
- 直接人工输入研究问题仍然可用，Query 库或生成 Worker 不可用时不会阻断现有 Deep Research 创建流程。

本地一键运行：

```bash
./scripts/start-local.sh
```

该脚本会启动主 API、研究 Worker、Query 生成 Worker 与 Web。无有效模型凭据时，人工 Query 库和 Deep Research 草稿能力仍可使用，自动生成任务会明确失败并显示原因。

## 测试

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/equipment_deep_research/query_library
```
