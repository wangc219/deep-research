# 智能对话与文档研究独立验收 · 2026-10-12

基于已同步 fork 的 `wangc219/main`：`5fdb9ec65d57c50b157e6b58eecc09753fa782e4`。用户选择复用现有智能对话，补齐独立文档研究的前端设置和文件交付。对照 Yuxi 固定版本 `ca21a30d64a58269e7c5eefffd1afe24e0ad6f62`，保留现有工作台和模块边界；本轮新增目录 ZIP，修复实际浏览器发现的 PDF worker 加载错误。

## 功能对照及结果

| 用户要求 | 实现及实际验收 |
| --- | --- |
| 统一智能体工作台 | 复用现有 ChatbotAgent、AgentPanel、WorkspaceFileList、AgentArtifactsCard、AgentFilePreview，不增加第二套聊天系统。 |
| 沙盒读写、可执行代码及访问范围 | 真实生产执行图、Docker 沙盒、PostgreSQL 检查点，读取 CSV、写入分析脚本并执行得到均值 20；工具拒绝 `/etc/passwd` 读取和 `/tmp/escape.txt` 写入。 |
| 文档、表格、网页、图表与代码产物 | 真实沙盒产出 Markdown、CSV、交互 HTML、SVG、PDF 和 Python；六个路径通过 present_artifacts 持久化并呈现交付卡片。 |
| 文件管理与复用 | 生产工作区服务展示目录层级、类型、大小；卡片保存文件到另一工作区目录，重新读取 Markdown 编辑结果；独立数据库集成检查会话工作区绑定。 |
| 在线预览及编辑 | 实际 Chrome 渲染 HTML 隔离 iframe 并执行交互，渲染 PDF canvas、SVG、代码和 Markdown；Markdown 编辑、保存、刷新重新读取通过。 |
| 单文件与打包交付 | 实际 HTTP 和浏览器下载文件、目录 ZIP；包仅含选定目录，拒绝其他身份、路径穿越和符号链接。 |
| 文档研究前端模型设置 | 专用管理员可保存地址、模型、密钥和思考强度；不回显密钥，空输入保留、显式清除，保存不调用模型；容器重启后保留。 |
| 文档研究文件交付 | 研究报告导出 Markdown、HTML、CSV、JSON；真实页面预览、编辑、刷新和下载 ZIP，保持专用身份及数据隔离。 |

“对齐”指上表用户要求的能力，不表示 Yuxi 全部功能和界面逐项一致。文档研究保持独立服务，模型配置不共享给原平台。HTML 交付为安全转义的文本报告；智能对话沙盒可产出交互网页。图文报告和图表由原智能体工具生成，本轮验证了合成样本产物，不证明真实模型在任意任务上的质量。

## 实际测试

- 文档研究 Python：276 passed；包括密钥脱敏、管理员撤权、交付授权/证据版本、并发保存冲突、持久化、大小限额与 ZIP 内容。
- 前端：522 passed；lint 和生产构建通过，保留既有大包提示。
- 工作区文件系统/服务最终专项：45 passed；此前工作区、交付与沙盒相关组合检查 161 passed。
- 独立 PostgreSQL/文件系统会话工作区集成：3 passed。
- 文档研究真实 Chrome + Vite + 生产服务/Engine + 合成 HTTP 模型：14 场景通过，0 浏览器异常、0 原平台 API 调用。最终服务重启后完整复测。
- 原智能对话生产组件 + 生产工作区/交付 HTTP 服务 + 真实沙盒文件：7 场景通过，0 浏览器异常，包含 390px 无页面横向溢出。
- 独立生产文档服务镜像实际启动、配置保存和重启：通过；配置 0600，响应 no-store，未调用外部提供商。
- Python Ruff/check/format、Git diff 空白检查通过。

核心可重复命令（仓库根目录，安装各模块锁定依赖后）：

```sh
uv run --no-project --python 3.12 --with pytest \
  --with-requirements document_research/requirements.lock \
  python -m pytest -q document_research/tests
cd web
pnpm test:unit
pnpm lint:check
pnpm build
```

在 backend 目录使用其环境执行 `PYTHONPATH=package:. python -m pytest -q test/unit/workspace/test_filesystem.py test/unit/services/test_workspace_service.py`。`web/test/fixtures/agent-workspace-parity.html` 仅是开发验收入口，复用生产组件；未加入产品路由，需要独立合成身份、实际工作区 API 和测试文件。

## 全量后端基线失败

本次 `test/unit -m "not slow"` 实际结果为 **2573 passed、11 failed**。将发布基线 `5fdb9ec6` 导出到干净目录，用相同依赖复测六个受影响测试文件，结果 **131 passed、同样 11 failed**，失败 ID 完全一致。见 [机器可读对照](backend-baseline-results.json)。没有修改这些无关测试来掩盖失败。

原因包括已移除的初始化/迁移脚本和旧工作流、worker healthcheck 的旧形式断言、并发默认值旧断言、依赖未提交真实数据库的 legacy 测试、缺少授权存根的旧路由测试，以及运行范围字段/知识库工具清单的旧断言。全量后端不能称为全部通过。

## 验收边界

模型是明确标记的确定性合成提供商；本轮没有从平台读取真实密钥，也没有重新调用真实智谱。独立文档入口使用生产鉴权；原平台工作区 HTTP 验收使用合成身份适配器，实际授权服务、文件系统、执行图、Docker 沙盒和 PostgreSQL 均为生产实现。这不等于完整生产登录、worker 调度和 SSE 浏览器链路都已验收。现有平台 5173 未启用专用文档服务，独立测试部署不等于现有部署已升级。

已通过的越界读写检查针对智能体文件工具和工作区 HTTP 授权；不将其称为执行任意恶意代码的完整操作系统安全审计。真实模型/知识库需由用户在前端或专用服务配置中提供可用凭据，报告专业语义、解析准确率和长期负载仍需单独验收。没有取得本次 GitHub Actions 成功结论。

## 证据

- [文档研究 14 场景](results.json)、[智能对话执行与工具返回](agent-runtime-results.json)、[工作区 7 场景](workspace-browser-results.json)、[容器持久化](container-results.json)、[源码指纹](source-fingerprints.json)。
- [模型设置](model-settings-light.png)、[研究交付编辑](delivery-markdown-edited.png)、[移动端研究入口](answer-mobile-dark.png)。
- [交互网页](agent-html-interactive.png)、[PDF 实际渲染](agent-pdf-preview.png)、[代码预览](agent-code-preview.png)、[工作区编辑](agent-markdown-edited.png)、[移动端工作区](agent-workspace-mobile.png)。
- ZIP 和 Markdown 附件均为合成验收样本；没有真实密钥、数据库、用户文档或账号资料。

源码指纹记录验收时的未提交实现，避免把基线 SHA 误作最终实现 SHA。部署按 [文档研究启动说明](../../../DOCUMENT_RESEARCH.md) 进行；回滚代码使用正常反向提交，保留专用数据和用户工作区，不能删除数据卷或强制重置历史。
