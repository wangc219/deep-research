# 文档解析研发入口验收记录

初验日期：2026-10-08；2026-10-09 的续作结论在本页末尾。基线 HEAD：`93d29fb7299d06e691da07a3ae8f42d7a1125338`；本地分支：`feature/document-parsing-research`。

2026-10-08 初验实现同仓库专用入口，保留原系统；没有修改或启动装备研发、武器研发或作战推演业务流程。原 `backend/` 源码最终无差异。没有迁移原数据库、覆盖交付包或推送 GitHub。

## 已通过

| 检查 | 基线 | 修改后实际结果 |
| --- | --- | --- |
| 原前端 `pnpm run test:unit` | 502/502 | 511/511，退出 0 |
| 原前端 `pnpm run lint:check` | 退出 0 | 退出 0 |
| 原前端 `pnpm run build` | 退出 0 | 退出 0，保留原大 chunk 提示 |
| 原仓库 `make check` | 补装测试组后 13/13 | 13/13；架构检查及编译通过，退出 0 |
| 新模块 `pytest document_research/tests -q` | 新模块不存在 | 108/108，退出 0；一条 Starlette TestClient/httpx 弃用提醒 |
| 新模块 Ruff 检查、格式检查 | 新模块不存在 | 均退出 0，13 个 Python 文件格式一致 |
| 真实 loopback HTTP + 合成模型 | 未执行 | 11/11 场景通过 |
| 真实浏览器 + 合成模型 | 未执行 | 10/10 场景通过；已检查浅色、深色、390px截图 |
| 真实公开资料读取 | 未执行 | 显式专用代理下三个官方 README 均成功，记录获取时间与 SHA-256 |
| 启动脚本与专用正常配置 | 未执行 | CLI 初始化、固定 loopback 启动与健康检查通过；正常配置没有合成模型 |

108 项新模块测试由 81 项 Engine/提供商、24 项服务、3 项静态隔离检查组成，不与前几轮通过数累加。

HTTP 场景包括独立认证、两个身份的跨库拒绝、损坏 PDF 可见失败、未同意模型外发拒绝、只用选定资料、空选库不退回全库、伪造来源拒绝、运行中编辑拒绝、取消迟到响应、删除证据后的报告访问拒绝、生成中撤销令牌后丢弃结果。

浏览器验证实际 Vue、HTTP、SQLite 和 Engine。模型响应来自明确标注的本机合成 HTTP 提供商，未调用真实模型。验证三项追问、带假设的计划、比较/步骤/拟定指标、原文陈述/推断、引用定位、刷新恢复、移动布局、取消和原平台凭据隔离。最终预览已停止合成模型，使用单独的正常配置目录。

证据：[HTTP 结果](validation/document-research/http-results.json)、[浏览器结果](validation/document-research/browser-results.json)、[公开读取记录](validation/document-research/public-fetch-final-results.json)。

![浅色合成报告验收](validation/document-research/desktop-report.png)

[深色截图](validation/document-research/dark-report.png) · [移动端截图](validation/document-research/mobile-report.png)

## 失败与修复

最终已执行的检查没有遗留失败；以下失败均保留在工作日志，不能从历史中删除：

| 失败 | 原因与处理 |
| --- | --- |
| Git DNS、HTTP/2、连接超时 | 改用 pinned commit 原始文件并逐个验证 Git SHA；中文路径首次未编码失败，修正后完成 1843 个文件校验。 |
| uv 缓存权限、离线依赖、pytest_asyncio 缺失 | 使用工作区缓存、联网安装，再按项目安装 test group；原 make check 重试通过。 |
| macOS 解析子进程退出 | DATA/AS setrlimit 不可用；Linux 保留硬限制，macOS 用父进程 RSS 监控，保留采样间隔限制。 |
| PATCH/run 覆盖状态 | 独立审查复现，新增并发回归先失败，SQLite 条件事务修复后通过。 |
| 推断附带伪造引文 | 新增反例先失败，修复为所有非空引文匹配来源连续原文，推断仍标待验证。 |
| Ruff 默认规则与格式检查失败 | 修正新文件的 import、嵌套 context、lambda 和格式问题，没有降低 gate。 |
| Chrome 默认沙箱无法启动 | 受审查权限下使用临时浏览器配置验收，无用户浏览器会话读取。 |
| 首次浏览器取消脚本超时 | 脚本新建任务漏勾模型外发同意，产品正确阻止运行；补全同意步骤后通过。 |
| 首次 HTTP 最后一项 403 | 脚本先删除证据再读关联任务，产品正确拒绝；调整检查顺序后通过。 |
| 子代理既有前端测试无法监听 | 环境 EPERM；主代理统一全量 511/511 通过。 |
| 公网提供商全部连接失败 | 本机需要代理；新增显式专用 `network.proxy_url`，默认仍不继承环境代理，真实三源重试通过。 |

## 未验证与边界

- **真实模型及智谱联调：NOT_RUN。** 没有提供相应真实配置，不证明账户权限、配额、真实引用质量或提供商 JSON 兼容性。
- **原完整 Docker 平台栈：NOT_RUN。** 本机无 Docker；原 Agent 全栈启动、PostgreSQL/Redis/Milvus/Neo4j/MinIO/Sandbox 协作未验收。
- **解析方案效果：NOT_RUN。** 没有运行 Docling/PaddleOCR/Unstructured 的解析性能或准确率实验；合成样本不能证明真实复杂表格质量。
- **Linux 资源限制、生产多租户、并发负载、公网部署：NOT_RUN。** macOS RSS 检测不是瞬时硬内存上限。
- **原共享知识图谱/知识检索增强：不在本轮实现中。** 新入口只展示其自己的证据关系，不写共享图谱，不注册共享 Agent 工具。
- 来源编号存在与引句匹配，不等于结论获得充分证据支持；真实报告需要人工复核。
- 基础文本提取不保存原件、不做 OCR、不保证复杂表格结构还原；公开资料仅三个固定官方项目来源，不是全网搜索。
- 取消停止本地结果处理，不能保证远端请求停止或不计费。服务重启后未完任务标记失败。

## 本地复验

在仓库根目录，先按使用说明安装专用依赖和测试工具：

```sh
../document-research-venv/bin/python -m pip install -r document_research/requirements.lock
../document-research-venv/bin/python -m pip install pytest pytest-asyncio ruff
../document-research-venv/bin/python -m pytest document_research/tests -q
../document-research-venv/bin/ruff check document_research
../document-research-venv/bin/ruff format --check document_research
uv sync --project backend --group test
UV_NO_SYNC=1 make check
```

前端：

```sh
cd web
pnpm install --frozen-lockfile
pnpm run test:unit
pnpm run lint:check
pnpm run build
```

浏览器与真实 HTTP 过程保留在本机审查目录的 `browser_acceptance.cjs`、`http_acceptance.py`、`synthetic_runtime.py`。它们专用于合成验收，不接入生产启动路径；公开源码中的 `validation/document-research/` 提供可复用的普通软件样本。

## 回滚

本分支有独立本地提交，提交信息为 `feat: add isolated document parsing research workspace`。在合并或继续修改之前，先用 `git log -1` 核对该提交，保留自己的未提交修改，停止专用服务。

若已合并该提交：用 `git revert <该提交SHA>` 生成逆向提交，再按原流程构建/重启前端。若仅试用此干净分支且未追加自己的改动：切回记录的上游基线分支 `main` 即可恢复原源码。不要执行强制 reset/clean。

本轮没有原数据库迁移。专用数据目录位于仓库外，回滚代码不会删除资料或密钥；先独立备份，需要清理时再由使用者明确删除。GitHub 尚未推送，因此本轮没有需要撤回的远端发布。

## 2026-10-09 部署接线复验

本次起始提交为 `2ed651d9b661cf3b768cc556c6a489ed4ffd2c57`，工作树干净；上游 main 仍为本页记录的基线。用户确认暂无真实模型或智谱账号/密钥，并选择发布到自己的公开 fork `3119744613-crypto/deep-research`。旧补丁和 ZIP 保留。

新增可选 Docker 覆盖层、专用容器入口及 Nginx 代理；Vite 支持显式专用服务目标。原 `api/worker` 的 Compose 定义经实际归并逐对象比较保持一致，原业务源码没有变更。

已实际通过：

- Python 3.12.8 新环境下专用模块 **112/112**，Ruff 和格式检查通过；新增 4 项容器初始化/鉴权测试。
- 前端 lint、**511/511** 单元测试、生产构建通过，既有大 chunk 提示保留。
- 固定 Python 版本并保留 test group 后，原 `make check` 的架构检查、编译、**13/13** 测试通过。相关既有 Nginx 静态配置测试单独 **3/3** 通过，不代表全后端单测通过。
- Docker **28/28** 检查通过：实际构建两个镜像、初始化新专用卷、只启动资料容器和 Web、`nginx -t`、未配置模型的健康状态、无令牌/错误令牌 401、有效独立会话、未知 API 路径 JSON 404、运行态端口/挂载/网络隔离。Linux ARM64 Docker Engine 29.5.2、Compose 5.6.0。验收结束仅清理该临时项目和空卷，未留下假装正常运行的合成服务。

证据：[Docker 专项结果](validation/document-research/docker-gateway-results-20261009.json)。所有真实模型与智谱调用仍 **NOT_RUN**。原完整平台的单独全新登录验收环境正在构建，当前未标记登录或完整 readiness 通过；原 worker 不在此验收启动范围。

失败与处理保留：旧 venv 解释器路径失效，另建环境；首次 `make check` 因 uv 自动重选 Python、移除 test group 而失败，固定解释器并禁用重复同步后通过；容器入口格式首次失败后修正；相关后端配置测试初次被非必要 fixture 导入阻断，明确限定静态配置回归后通过；Colima 镜像直连超时，经本机显式代理重试成功；原平台 classic 构建发现缺 buildx 后中止，补齐插件继续验收，不将中止算通过。

回滚本次部署接线时，先停止 `document-research` 容器，再用原 Compose 配置重建 Web，保留专用卷。代码可对本次 `fix: wire isolated document research container deployment` 提交执行 `git revert`。若同时撤销初版入口，还需回滚 `2ed651d9b661cf3b768cc556c6a489ed4ffd2c57`；不要强制 reset/clean 或删除用户数据。

## 2026-10-09 交付收口

**已发布**：用户公开 fork [3119744613-crypto/deep-research](https://github.com/3119744613-crypto/deep-research) 的 `main` 已实际快进到实现提交 `f5cbc76ce0c0a9aceec90c48149b3dd3a5a7d683`，GitHub API 核验一致，包含初版提交 `2ed651d9b661cf3b768cc556c6a489ed4ffd2c57`。未向 wangc219 的仓库推送。此节文档随后单独提交更新。

**失败 / 阻断**：原平台固定的 `quay.io/minio/minio:RELEASE.2023-03-20T20-16-18Z` 在本次检查中无法匿名获取；官方 Docker Hub 同版本也返回鉴权拒绝。官方同版本 ARM64 二进制及 `.sha256sum` 归档均 HTTP 410，未取得可信的同版本替代制品。没有使用第三方镜像或擅自升级存储版本。其余 7 个运行镜像 manifest 已确认包含 Linux ARM64，这只证明架构清单可读，不是完整启动通过。

为避免把不完整栈误交付为可用系统，确认该依赖阻断后中止原平台 BuildKit 构建（退出 130）。原实例 `compose ps` 为空，未启动原 API/worker、未创建管理员、未执行领域任务。全栈登录、持久存储协作、完整 readiness 仍 **NOT_RUN**。模型和智谱因用户暂无账号/密钥仍 **NOT_RUN**。证据：[依赖检查结果](validation/document-research/platform-dependency-results-20261009.json)。

本次新建的 Colima VM 已停止以释放内存，保留安装工具、镜像缓存与验收配置；不是常驻部署。新增资料入口 28 项真实容器检查与前述单元/构建结果仍有效，不受原 MinIO 下载阻断影响。

剩余工作是取得可用且经过核验的原平台 MinIO 制品后重新执行全栈验收，以及在提供真实模型和智谱专用配置后执行真实联调。没有执行的这些项目不能写成通过。

回滚代码可先 `git revert f5cbc76ce0c0a9aceec90c48149b3dd3a5a7d683`，需要撤销全部新增入口时再 `git revert 2ed651d9b661cf3b768cc556c6a489ed4ffd2c57`；在自己的分支处理后推送自己的 fork，勿强推上游。停止专用容器并用原配置重建 Web，保留专用数据卷。最终说明文档是单独提交，可按需保留审计记录。

## 2026-10-11 真实智谱知识库与模型联调（本地续作）

代码起点HEAD为843a7c4，工作树起初干净；本轮不覆盖旧交付包、不修改原平台backend。用户在仓库外私有配置填写密钥与指定库，未把凭据提交源码。真实提供商调用使用合成TXT，未发送其他本地资料。当前这批兼容修复在本地工作树，尚未提交/推送。

### 已通过

- 真实智谱鉴权和目标库详情读取；先确认空库，用户上传后，两次检索分别命中测试编号和三类案例。来源元数据及范围校验通过；空白归一化后与合成原文一致。
- `glm-5.3-flash` 简短JSON调用，以及真实智谱检索→现有Engine→真实模型→结构/引用ID/原文引句校验→报告返回。最终一次34.98秒，输入2259、输出1883、合计4142tokens；返回1来源、0候选比较、2项实验、4条图谱关系，明确not_measured。
- 最终专用模块127项测试，Ruff检查和14文件格式检查；make check架构/编译及13项通过。前端未改，本轮没有重跑前端或浏览器测试；此前结果保持原日期，不作为本轮真实模型浏览器验收。

### 失败、修复与剩余问题

- 本机JSON缺分隔逗号，备份后只补一个逗号；模型key仍为示例说明文字，导致UnicodeEncodeError，备份后从已验证的本机智谱key复制。未输出密钥。首试日志的model_invoked只表示进入调用函数，不证明已发出请求。
- 首次完整模型请求连接失败或超时；关闭thinking的短诊断被HTTP400/1210拒绝。该型号始终思考，改用可选reasoning_effort=low后短JSON和报告请求成功。没有以此断言长请求失败的唯一原因。未配置该选项时保留旧请求，非法值在发送前拒绝。
- 首份报告把列为候选当作优点、用主题引句支持工具适用性；收紧提示后比较为空。第二份实验方案混淆TXT说明与实际表格样本；继续明确需另制PDF/DOCX和扫描图像，最终样本逻辑修正。原模型输出与复核记录均保留。
- **内容未全面验收**：最终待验证图谱推断仍带有所引来源未提及的候选名；F1计算中的TP/FP/FN、对齐方式与部分基线仍待专业复核。结构/引句匹配只证明格式与原文存在，不证明语义充分支持，提示词收紧不是确定性的语义保证。不把该示例报告当作正式选型报告。
- make check首次受工具隔离影响无法读取默认uv缓存，使用本轮临时缓存及既有Python3.12环境后通过；未改依赖锁。官方个别文档页超时保留，未作账号失败。

### 未验证

真实复杂表格解析效果、三方案实测比较、完整专业报告与图谱语义质量、浏览器中真实模型流程、流式输出、负载和长期稳定性未在本轮验收。原完整平台部署阻断仍沿用2026-10-09记录。

### 证据与回滚

私有目录保留每次脱敏调用记录、模型原始输出和带复核说明的zhipu-live-acceptance-report-20261011.txt，不将账号库ID、密钥或文档下载地址放入本仓库。配置修改前分别保存0600备份；本次补丁保存于仓库外deep-research-model-integration-20261011.patch。回滚代码前先保存后续修改，检查补丁逆向应用，再逆向应用该补丁；不要使用reset或覆盖整个仓库。配置回滚应选择所需版本备份（最早两份保留了待修的格式/占位错误，不能误当可运行配置），或仅删除新增model.reasoning_effort恢复默认；不要删除知识库或数据目录。


## 2026-10-11 检索、证据问答与图谱约束增量验收

本轮基于 `843a7c4d74fee36cfb58546b9940ceaad4bac3c3` 及开始时已有的 7 个未提交修改文件。未覆盖前一轮模型兼容/提示修复；未改原 backend、默认 Compose 或数据库架构。新增能力位于独立 `/document-research`。

### 已通过（实际执行）

| 项目 | 结果与范围 |
| --- | --- |
| 修改前基线 | Python 127 passed；前端 511 passed；前端构建通过。首次前端测试受沙箱监听限制失败，获准本机监听后重跑通过。 |
| 修改后后端 | Python 263 passed，1 条既有 Starlette/httpx 弃用警告；Ruff check/format 通过。包含有据回答、引句/来源拒绝、图谱端点过滤与去重、检索授权、撤权、公开词隔离、危险/带凭据 URL 防护。 |
| 修改后前端 | 517 passed（包含隔离入口定向 15 项），lint 和最终构建通过。保留既有 chunk >500k 提示。 |
| 旧架构检查 | make check 的架构约束、编译及 13 项旧测试通过。没有运行整个原平台集成测试。 |
| 浏览器验收 | 真实 Chrome + 本机实际 HTTP + 合成提供商，15 场景通过、0 失败；包括预览、空命中/错误、取消、晚响应丢弃、选库变化、引用展开、图谱过滤、刷新恢复、亮暗主题和 390px 显示。未调用原平台 API 或混用原平台凭据。 |
| 真实证据问答 | 用户已上传的合成 TXT，经真实智谱检索和配置模型，最终得到 2 条带逐字引句的回答及 1 条端点已锚定的图谱关系；该次无边被移除。没有运行文档解析器实验。 |
| 真实公开检索 + 知识库 + 深研 | 显式公开查询 `site:docling-project.github.io/docling table` 返回 3 条允许的官方资料摘要，与 1 条智谱片段组成 4 条证据。模型生成 1 个有来源的 Docling 比较条目；另两候选列为缺口。6 条未满足端点规则的图谱边被移除并明确提示。报告结构、来源 ID、原文引句校验通过，不等于方案语义已充分核实。 |
| 已配置本机服务 | 页面 4196、专用服务 4198 已启动；通过真实前端代理检查页面、health、session、libraries、retrieve 均 HTTP 200；检索命中合成编号，签名下载链接未返回；此 HTTP 检查未调用生成模型。验收专用 4206/4208/4209 服务已关闭。 |

浏览器截图仅包含合成测试数据：[浅色问答](validation/document-research/retrieval-upgrade-20261011/answer-light.png)、[深色问答](validation/document-research/retrieval-upgrade-20261011/answer-dark.png)、[移动端深色](validation/document-research/retrieval-upgrade-20261011/answer-mobile-dark.png)。完整场景记录见 [浏览器结果](validation/document-research/retrieval-upgrade-20261011/browser-results.json)。

### 失败、修复与保留的限制

- 第一次真实问答失败：模型生成的引句不完全匹配原文，系统拒绝保存。第二次复测通过但 2 条图谱边被移除。随后提示补充“每条答案对应一项事实、复制连续原文、直接抽取实体”的例子，最终复测 2 条回答和 1 条关系通过。没有关闭逐字校验，也不保证以后模型永不生成无效引句。
- 普通公开关键词 `Docling` 及一条宽泛查询返回无关/非允许来源，过滤后 0 条可用；限定官方站点后得到 3 条片段。宽泛搜索相关性仍有限，没有通过放宽来源校验掩盖此问题。
- 初次 Ruff 检查有导入格式、异常兜底规则和 startswith 写法问题，修复后通过；网络文档读取曾超时/证书失败，改用正常 TLS 的系统客户端获取官方文档，未关闭证书校验。
- 对上轮真实深研报告离线重验，原 4 条边全部被新端点规则移除；新规则是保守的词面锚定，不能自动证明因果/适用性等关系语义。
- 公开搜索仅引用服务返回摘要，未抓取或核对网页全文。问答每次重新检索，不自动带入历史，不提供逐字流式输出；本地检索仍为关键词匹配。

### 未验证

- 真实复杂表格样本上的解析准确率、OCR、跨页/合并单元格实验，三种解析器的实际性能与最终选型。
- 所有回答、优缺点、实验指标和图谱关系的专业语义正确性；图谱规则可能过滤有用但采用改写实体的关系，仍需研发人员复核。
- 真实提供商条件下的页面全流程操作、远端计费取消、长时间可靠性和生产多用户部署。浏览器验收用合成 HTTP；真实提供商另经 Engine 和本机 API 验证，不混称一体化浏览器实测。
- 原完整平台 Docker 部署、本轮 GitHub 发布；本轮只启动独立通用入口，代码尚未提交或推送。

### 回滚

先停止本次本机入口服务，保留专用数据目录。仓库外 `../retrieval-upgrade-20261011T094406Z/` 保存修改前差异 `before.patch`、源码快照 `before-sources.tar.gz` 和本轮增量 `retrieval-upgrade.patch`。后者仅撤销本轮改动，保留开始时已有的 7 个修改文件。不要使用 `git reset --hard` 或覆盖整个交付包。

在仓库根目录先检查，再按需执行：

```sh
git apply --reverse --check ../retrieval-upgrade-20261011T094406Z/retrieval-upgrade.patch
git apply --reverse ../retrieval-upgrade-20261011T094406Z/retrieval-upgrade.patch
```

实际回滚未执行；若此后继续修改，应重新检查冲突，不能强制覆盖。恢复代码后重启相应服务即可；本轮没有更改私有密钥配置或迁移数据库。


## 2026-10-11 GitHub 发布前最终复核

用户明确授权验证并发布至公开 fork `3119744613-crypto/deep-research`。GitHub 登录账号、ADMIN 权限和默认分支 main 已核实；读取远端 main 与本地基线 843a7c4 一致，没有覆盖远端新提交。首次 Git 直连超时，沿用本机既有代理重试成功，未修改永久网络配置或降低 TLS 校验。

- 后端重新执行：263/263 passed，Ruff 与格式检查通过；make check 的架构检查、编译与 13 项旧测试通过。
- 前端首轮 517 项通过；独立审查发现并修复启动响应丢失后不恢复监测的问题。最终 520/520 passed，专项 18/18，lint 与构建通过，保留既有大包提示。
- 专项浏览器 3/3 通过：真实接收启动 HTTP 202 后故意丢弃响应，问答自动启动与深研手动启动均无需刷新、无需重复 POST，分别轮询至完成。2 个任务恰好只有 2 次启动和 2 次合成模型调用。原 P2 问题已复测关闭。
- 之前的 15 项浏览器综合检查与真实提供商调用保留原日期和范围；本轮专项仅使用本机合成提供商，没有重复收费调用。专业语义、解析性能和完整原平台部署仍未验证。
- 待提交文件实际密钥/令牌值和凭据特征扫描通过；没有把真实配置、数据库、模型原始输出或签名下载链接加入提交。

专项证据：[结果 JSON](validation/document-research/publication-20261011/results.json)、[问答恢复截图](validation/document-research/publication-20261011/answer-response-loss-recovered.png)、[深研恢复截图](validation/document-research/publication-20261011/research-response-loss-recovered.png)。合成测试服务已停止，用户当前本机 4196/4198 服务保留。

GitHub 云端检查与实际推送结果将在发布确认后单独追加，不将本机通过记成云端通过。前文“尚未提交/推送”是对应阶段的历史状态。


## 2026-10-11 发布已确认

已将完整功能与发布前修复提交 [`2116cd4`](https://github.com/3119744613-crypto/deep-research/commit/2116cd4782fb88e935dc5af8d2776444c06be50b)，并通过普通快进推送更新用户公开 fork 的 `main`（843a7c4 → 2116cd4）。GitHub API 返回的远端 main 精确 SHA 与本地实现提交一致。未修改 wangc219 上游，未强推。此前“尚未发布”记录保留为历史过程。

本机最终验证：后端 263、旧架构/设置 13、前端 520 全部通过；lint、构建通过。沿用本轮此前的 15 项综合浏览器验收，并新增 3 项发布专项回归通过。专项仅使用合成 HTTP；真实提供商验收见前文，不声称专业报告质量、完整平台部署或生产稳定性通过。

GitHub Actions 与本机结果分开：发布后首次查询未返回本提交的运行记录，尚未取得云端检查结论，不计为通过。本说明另以文档提交保存，不改变已验证代码。

### 已发布版本的回滚

先保存自己的后续修改并停止受影响的本机服务，在自己的分支执行 `git revert 2116cd4782fb88e935dc5af8d2776444c06be50b` 可生成反向提交，审核后正常推送自己的 fork；不要强推或重置历史。没有实际执行回滚。该实现提交同时包含上轮模型兼容修复与本轮检索增强，撤销它会一起撤销这批未发布前的改动；专用数据与密钥配置不受 Git revert 管理，不应删除。仓库外保留发布前内容副本以供选择性恢复。

## 2026-10-12 同步到 wangc219/main 后的独立复验

fork 的 5 个提交已以普通快进方式同步至 `wangc219/deep-research` 的 `main`。同步后两边远端均为 `47958e74362b929bfd3e35092e3fdf9437242cdc`；保留原始提交历史、全部 65 个文件的增量和本地未提交文件。原 backend 相对基线仍没有源码差异。

本次仅补充 Python 3.12+ 已支持的标准别名：解析超时使用内置 `TimeoutError`，提供商时间戳使用 `datetime.UTC`，解决 Ruff 0.17 的三处旧别名提示。没有修改模型、检索、权限或任务协议。

实际复验结果：

- 专用 Python 测试 263/263，通过；保留一条已有 Starlette/httpx 弃用提示。Ruff 检查及 18 文件格式检查通过。
- 原平台 `make check` 的架构检查、编译及 13 项回归通过。前端在当天同步验证中 520/520、lint、生产构建通过；本次后续没有修改前端源码。大包提示保留。
- 最终代码在真实 Google Chrome、实际 Vue/Vite 代理、生产 `create_app`/Engine/解析子进程/SQLite 下通过 12 个综合场景。只有外部模型为明确标记的 loopback 合成 HTTP 提供商，没有使用真实账户或原平台资料。覆盖四种格式上传、损坏 PDF 提示、选库/空选择/零命中、无模型调用的检索预览、逐字引用与来源跳转、图谱端点过滤、刷新恢复、亮暗主题、390px 布局、两种启动入口的 202 响应丢失恢复、取消与迟到响应、伪造引句拒绝、提供商错误、身份隔离及删除。没有浏览器异常或原平台 API 请求。
- 可选 Compose 配置、独立服务镜像和生产 Web 镜像构建通过。在独立验收项目实际启动服务与 Nginx，验证专用配置 0600、health、鉴权、上传/解析/预览/检索/删除、Nginx 配置和代理，以及生产静态页面与未配置模型提示均通过。没有启动该项目的原 API/worker/数据服务。

首轮失败与处理：浏览器删除场景的按钮名称匹配写错，修正验收脚本后完整重跑；Docker 首次 HTTP 检查早于服务 ready，改为等待健康检查后复验通过。这两项是验收脚本问题，没有以修改产品行为绕过。标准别名修正后重新执行 Python、Ruff 和全部页面场景。

证据：[结果与源码指纹](validation/document-research/main-sync-20261012/results.json)、[引用问答](validation/document-research/main-sync-20261012/answer-desktop-light.png)、[移动端深色](validation/document-research/main-sync-20261012/answer-mobile-dark.png)、[深研启动响应丢失恢复](validation/document-research/main-sync-20261012/research-response-loss-recovered.png)、[Docker 静态入口](validation/document-research/main-sync-20261012/docker-static-entry.png)。验收服务已停止、独立合成测试卷已移除，4296/4297/4298 均无监听。

运行范围：现有 5173 页面没有启用可选文档研究服务，其专用 API 检查返回 502；默认 Compose 不启用新服务属于本轮原有部署设计。本次独立部署验收成功不代表已将新服务启用到现有完整平台。未提供专用配置路径，本次没有重新调用真实智谱知识库、公开搜索或真实模型；此前真实提供商记录仍保留原日期。复杂表格保真、OCR、解析性能、专业报告语义与生产负载仍未验证。GitHub Actions 查询受到匿名 API 限流，未取得云端结论，不将本机结果标为云端通过。

## 2026-10-12 智能对话工作区与文档研究交付验收

按用户选择复用原智能对话，保留原平台沙盒和工作区，增加目录 ZIP 下载、修复 PDF 预览 worker；独立文档研究增加前端模型设置和 Markdown/HTML/CSV/JSON 文件交付、Markdown 编辑持久化及 ZIP 下载。对照 Yuxi 固定版本，功能映射、具体证据和限制见 [本轮完整验收记录](validation/document-research/delivery-20261012/README.md)。

真实生产 ChatbotAgent 执行图、Docker 沙盒和独立 PostgreSQL 检查点完成 CSV 分析、脚本执行及六种文件交付，越界文件工具调用被拒绝。真实 Chrome 通过文档入口 14 场景及智能对话生产组件 7 场景，覆盖交互 HTML、PDF canvas、图表/代码预览、Markdown 编辑和文件/目录下载。文档服务生产容器通过配置保存、0600/no-store 和重启持久化检查。模型为合成提供商；工作区 HTTP 使用合成身份适配器，不声称完成真实提供商或完整生产登录/worker/SSE 验收。

最终文档 Python 276、前端 522、工作区最终专项 45、独立数据库集成 3 项通过；lint、构建和 Ruff 通过。全量后端为 2573 passed、11 failed；在干净的原 main 基线复测受影响文件，同样 11 项失败，无新增失败，详见记录。现有完整平台尚未启用专用服务，用户需按启动说明部署并通过前端填入真实模型配置。此前阶段的“未发布”描述保留为历史状态。
