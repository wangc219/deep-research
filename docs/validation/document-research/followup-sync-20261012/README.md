# 第二次 fork 同步及可选检索验收 · 2026-10-12

我们仓库基线 `a952347052dbd96e573b5d912bdf0e64da695cca`；合并 fork 最新 `f4bdcf1cbfc0484503a8669829e4ce1ecdcd5d9e`，包含实现 `a9da1fce96280b0353a1ed3d16e93d28e46500a6` 和发布记录。保留 fork 原提交历史，以及我们已有的前端模型设置、文件交付、Markdown 编辑、目录 ZIP 和 PDF 预览修复。

## 融合后的行为

- 完成问答后可继续追问，或转为细化深研方案；重新检索最近最多三个用户问题背景，重新确认外发，不沿用旧模型结论作为证据。
- 中英文 BM25 排序、同文档重复片段合并、候选名称提及/缺口、无候选证据的比较过滤、证据关系关键词/类型/来源筛选及原文定位。
- 追问与原有模型设置、四格式文件交付同时可用。子任务生成独立交付副本，不继承父任务 Markdown 编辑；资料版本失效会撤销报告和交付访问，运行中的任务仍可脱敏停止。
- 智谱知识库为可选来源。未配置时可使用本地资料问答/研究；已配置但未勾选时不调用，勾选后只调用本次授权的库。
- 公网检索默认 Open Websearch，不依赖智谱知识库或密钥。管理员可在前端设置提供商、地址和引擎；任务勾选公网检索后仅发送单独填写的公开关键词。保存设置不搜索，不自动把私有问题变成搜索词，不自动切换提供商。
- 可选容器覆盖层新增独立 document-websearch，与文档服务使用专用网络；未修改原平台 API、worker、数据库、原搜索服务或用户配置。旧专用配置缺少搜索字段时使用明确的专用容器地址或本机默认地址，可在前端覆盖；原来使用智谱公开搜索的用户可显式切回智谱。

## 最终检查

| 检查 | 结果 |
| --- | --- |
| 文档研究 Python | **373 passed**；包含旧设置/交付与新追问/检索回归、可选智谱、搜索 HTTP 契约、撤权、密钥不回显、无效设置原子拒绝、旧配置的专用地址。保留既有 Starlette/httpx 弃用提示。 |
| 前端单元测试 | **530 passed**；最终 lint、生产构建通过，保留既有大包提示。 |
| 原架构/编译与相关回归 | 架构检查、compileall 通过；13 项架构/设置测试通过。初次 make check 使用没有 pytest 插件的环境失败，显式启用 backend test 依赖组并使用 python -m pytest 后通过相同 13 项。没有修改 Makefile 或测试断言。 |
| Python 风格与 Git | Ruff/check/format、diff 空白及冲突标记检查通过。 |
| 实际浏览器基础流程 | **14/14**：实际 Chrome、Vite、生产服务/Engine/SQLite，覆盖设置、上传四格式、预览、问答、交付编辑/刷新/ZIP、取消、错误、断线恢复和隔离。模型为明确标记的合成 HTTP 提供商。 |
| 实际浏览器融合流程 | **6/6**：真实 Open Websearch 公网预览、无智谱配置、本地问答、组合图谱筛选/原文/手机深色、追问与交付隔离、转深研 ZIP、资料失效后的脱敏停止。两个浏览器流程均无 JS 异常或原平台 API 请求。 |
| 真实公网检索 | 独立固定镜像的 Open Websearch 实际联网；生产 HttpProviders 在无智谱配置下保留 4 条官方/论文摘要。搜索摘要不等于阅读全文，排名与数量可能随搜索引擎变化。 |
| 独立生产容器 | 最终文档服务镜像构建、启动、前端设置 HTTP 契约、专用网络连接真实 Open Websearch 通过；无智谱配置、无选库的公网预览保留 6 条公开来源，未调用模型，no-store 与密钥不回显通过。 |
| Compose | 完整可选覆盖层 config --quiet 通过。工作树没有私有 .env，检查时仅指定原目录作为 Compose 项目目录；没有输出环境值或部署原平台。 |

此前全量原平台后端的 11 项基线失败见 [上一轮对照](../delivery-20261012/backend-baseline-results.json)。本轮未修改原 backend 源码，也未重跑完整平台后端、数据库/worker E2E；不将历史结果说成本轮全量通过。

## 失败过程与验收边界

首次融合浏览器脚本使用了下拉框错误的精确名称，停止按钮又被全局忙碌文案重复匹配；修正定位后完整复测。某次组合引擎查询只返回非允许来源，保守过滤后零保留；使用公开关键词 Docling document conversion 和 DuckDuckGo 获得原始官方/论文来源，未放宽来源规则。手机长页截图出现浏览器拼接问题，最终使用实际视口截图显示关系筛选界面。失败截图未作为最终通过证据。

模型生成仍为合成提供商。本轮没有重新调用真实智谱知识库/模型，不证明真实模型报告专业语义、复杂表格解析性能、搜索相关性评测或生产负载。搜索源仍限文档解析模块允许的官方资料与论文，未增加网页全文抓取。原智能对话和工作区功能沿用此前验收；用户当前本地 AMiner 等未提交改动未合入本次提交。

现有平台部署仍未启用新增专用服务，本轮只验证独立环境；使用步骤见 [文档研究说明](../../../DOCUMENT_RESEARCH.md)。原平台与用户文件保持不变。GitHub 云端 CI 未取得成功结论，本机检查与云端分开记录。

## 证据及复验

- [基础 14 场景](results.json)、[融合 6 场景](followup-browser-results.json)、[真实公网检索](openwebsearch-live-results.json)、[生产容器](container-results.json)、[验收源码指纹](source-fingerprints.json)。
- [公网设置](search-settings-light.png)、[真实搜索预览](public-search-light.png)、[追问背景](followup-background-light.png)、[证据筛选手机深色](graph-mobile-dark.png)、[追问研究及交付](followup-research-delivery.png)、[失效停止入口](revoked-running-stop.png)。
- ZIP 和 Markdown 附件只含合成验收数据，没有密钥、专用令牌、数据库或真实用户文档。源码指纹标记已验收的合并实现，避免误把基线 SHA 说成最终代码。

复验命令：`uv run --no-project --python 3.12 --with pytest --with-requirements document_research/requirements.lock python -m pytest -q document_research/tests`；在 web 目录执行 `pnpm test:unit`、`pnpm lint:check`、`pnpm build`。独立真实搜索容器、端口及合成专用卷在验收后清理，原平台容器保留。回滚代码使用正常反向提交，保留用户资料与私有配置，不能强推或删除数据卷。
