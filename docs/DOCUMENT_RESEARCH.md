# 文档解析研发入口

这个入口为普通软件研发任务生成有来源的方案比较、建议实验步骤与拟定验收指标。示例场景是“文档解析服务对跨页、合并单元格等复杂表格识别不准”。它不运行候选解析方案的性能实验，也不声称已解决识别准确率问题。

入口位于原 Vue 前端的 `/document-research`，原 Agent、知识门户和其他路由保留。菜单连接的是同仓库新增服务；它没有注册为原平台 Agent 的工具，没有修改原共享知识库、图谱或装备研发流程。

## 当前能力与限制

- 建立专用本地资料库，上传 PDF、DOCX、UTF-8 TXT/Markdown，查看提取文本和解析失败原因。上限为每文件 10 MiB；扫描 PDF 没有 OCR。仅保存提取文本、原文件名和适用时的页码，不保存原文件下载；DOCX/TXT/MD 不制造页码。复杂表格结构与图片不能由基础文本提取保证还原。
- 每个任务显式选库，空选择不会读取全部知识库。知识库、文档、任务和报告以独立身份授权；权限在检索及结果保存、读取时重新检查。
- 连接由服务端管理员配置的已有智谱知识库，只读检索，不上传、同步或删除智谱文档，不改动现有平台知识库。
- 最多追问解析器版本、正确结果、运行约束三个关键问题；允许带明确假设继续。
- 模型报告包含候选方案、优缺点、建议实验、指标、推荐、证据缺口及引用。所有性能结论都标记“未实测”。没有模型配置时明确报错，不用模板假装模型已运行。
- 图谱关系区分来源陈述与待验证推断；两类关系都要求连续原文引句，以及引句中可定位的主体、客体。缺少依据或重复的边会被移除并显示原因；未知来源、伪造引句仍拒绝整份结果。端点校验不证明关系语义成立，旧报告会标注端点未校验。
- 公开资料有两个可分别启用的来源：固定官方 README，以及公网检索。默认公网提供商为 Open Websearch，无需智谱知识库或密钥；也可显式选择智谱公开搜索。公开搜索仅发送单独填写的 1–70 字符关键词，筛选官方文档/代码和论文原始来源，不发送完整私有问题或文档。搜索返回的是摘要，未读取全文，也不代表已核实全文。
- 任务按阶段显示状态，支持取消本地等待和重新进入页面继续查看。它不模拟逐字流式回答，也不保证远端提供商停止计费。服务重启后未完成任务明确失败，不冒充已恢复执行。

## 检索预览、证据问答与深研方案

1. 连接专用服务，勾选本次可使用的本地库或智谱库，填写问题。
2. 点击“预览检索结果”，先检查每个来源的成功、空结果或失败状态、命中文档和原文。此步骤不调用生成模型，不需要勾选模型发送同意。本地按中英文词项进行 BM25 排序（词频饱和、片段长度归一），智谱使用其远程检索服务；空命中不等于知识库没有文档。
3. 选择“证据问答”获取逐条带原文的回答，或选择“深研方案”生成比较、实验计划及待确认指标。生成前须明确同意向配置的模型发送当前问题和检索片段。
4. 点击引用即可展开并定位原文。来源清单区分“本次提供给模型”与“被实际引用”；搜索摘要单独标记，不能当作阅读完整网页的证明。

完成的任务显示“研究文件交付”，提供 `report.md`、`report.html`、`evidence.csv`、`report.json` 的预览、单文件下载与 ZIP 打包。Markdown 可在线编辑保存，刷新和服务重启后保留；编辑的是交付副本，不改变原始报告、证据或其他格式。并发编辑冲突会要求重新打开，避免覆盖另一份修改。每个文件最多 4 MiB，交付读取、保存和下载继续检查任务归属、资料授权及本地资料版本。

原智能对话继续使用已有工作台、沙盒、文件目录与聊天交付卡片，支持 Markdown、HTML、PDF、图片图表及代码预览。个人工作区和会话工作区的目录可通过“打包下载 ZIP”交付；知识库目录不提供此操作。目录包最多包含 5,000 项、32 层目录和 256 MiB 未压缩内容，遇到符号链接或特殊文件会拒绝整个下载。本入口的研究交付保存在专用数据目录，不写入原智能对话数据库或工作区。

每个问题重新检索选定资料。完成回答或报告后，可点“继续追问”或“据此细化方案”：界面列出将沿用的最近最多 3 个用户问题，每个最多 2000 字符，过长或较早的背景会明确提示截断。背景只用于理解当前问题，不包括旧模型回答或旧证据；服务端重新核验历史任务所属用户、资料库范围和资料版本。追问固定同一资料范围，更换库请点“改为独立新问题”。公开资料、公开搜索词与模型外发选项均须重新选择；选中智谱库时，当前问题优先、随后附最近背景，合计前 1000 字符用于知识库检索。仍不提供逐字流式输出。任务支持取消、刷新恢复状态和权限变更后丢弃结果；启动响应丢失时会自动查询已有任务，不重复发送启动请求。切换选库、问题或凭据会清除在途预览。停止等待不能保证远端请求尚未执行或停止计费。

同一文档中仅空白不同的重复片段会合并，保留原文、首个引用位置及其他片段标识；不同文档来源分别保留。本地检索仍是词项匹配，尚未引入语义向量，也没有真实相关性数据集的效果结论。

“候选资料提及”显示本次保留的证据原文是否出现 Docling、PaddleOCR、Unstructured 名称；提及不等于功能证据充分或性能验证。深研比较若引用的片段未提及对应候选，会移除该比较并显示缺口。图谱的“证据关系”可按主体/关系/客体关键词、原文陈述或推断、来源组合筛选；点引用可展开原文，清除筛选可恢复全部关系。

智谱知识库是可选来源：不配置、不勾选均不会发起智谱知识库请求，也不会阻止本地资料问答/研究或 Open Websearch 公网检索。配置后只访问当前任务勾选且授权的库；知识库检索与公开网络检索独立启用。

管理员连接后可在“模型设置 → 公网检索”选择 Open Websearch 地址和搜索引擎。本机默认为 `http://127.0.0.1:3210`，可选容器覆盖层使用独立 `document-websearch` 服务；不读取原平台 `.env` 或智谱密钥。只有任务勾选“启用公开网络检索”才调用搜索，保存设置不发送搜索请求。服务未启动、超时或返回错误会明确报错，不伪装成零命中，不自动切换提供商。

真实 Open Websearch 联调中 `Docling document conversion` 配合 DuckDuckGo 返回可用官方/论文摘要；某些引擎对 `site:docling-project.github.io/docling table` 会返回不相关网页而全部被过滤。可调整公开关键词/搜索引擎或启用“补充官方项目资料”，不能把无关网页当作证据。选择智谱公开搜索时使用专用 `zhipu.api_key`，不要求选中远程库；账号须具备相应搜索权限和额度。升级前使用智谱公开搜索的配置，可在前端显式选择“智谱公开搜索”保留该提供商。

新增接口 `POST /document-research-api/retrieve` 返回有界来源、限制说明与各来源状态；任务新增可选 `mode`（默认 `research`，或 `answer`）及 `allow_web_search`（默认关闭）。旧任务兼容默认研究模式，不迁移原平台数据库。知识库签名下载地址不送入模型或新结果，保留文档与切片标识用于追溯。

公开搜索接口依据[智谱官方 Web Search 文档](https://docs.bigmodel.cn/cn/guide/tools/web-search)和[API 参考](https://docs.bigmodel.cn/api-reference/工具-api/网络搜索)，使用独立 `web_search` API 的 `search_std`，不注册到原平台 Agent。

## 与现有架构的关系

现有 `platform_core` 的知识检索端口同时服务装备研究和深研。直接注册新的知识库类型会将其开放给这些调用链。因此，本入口是对 `docs/ARCHITECTURE.md` 中统一身份、数据平面原则的一项明确例外，用于落实已确认的通用软件研发范围：

1. 专用 Python 进程、数据目录、鉴权令牌和提供商配置；不读取平台 `.env` 或共享凭据。
2. 不导入 `platform_core`、`equipment_deep_research` 或 `knowledgegraph`，不注册共享工具、Agent preset 或 MCP。
3. 不写入平台 PostgreSQL、Milvus、Neo4j、项目报告或原 AgentRun。
4. 不修改默认 Compose 网络、数据挂载或 worker 配置。不要给原平台 worker/sandbox 挂载专用数据目录或传递专用令牌。
5. 本机 CLI 只绑定 `127.0.0.1`；可选容器仅在专用容器网络监听，由 Web 的 loopback 端口代理。前端专用 API 不发送原平台 cookie/token。

这属于进程、凭据和调用链隔离，不是同一操作系统用户之间的强安全沙箱。若部署到共享主机，需用独立系统用户/容器和访问控制保护数据；当前交付未声称通过生产多租户或网络隔离验收。

## 本机启动

原完整平台仍使用根 README 的 Docker 启动方式。下面命令只启动新增入口服务和原 Vue 前端，不代表完整平台后端已经运行。

需要 Python 3.12/3.13、Node 22+、pnpm。先在仓库根目录为专用服务建立环境（示例用仓库外的相邻目录）：

```sh
python3 -m venv ../document-research-venv
../document-research-venv/bin/python -m pip install -r document_research/requirements.lock
DOCUMENT_RESEARCH_PYTHON=../document-research-venv/bin/python \
  sh scripts/document-research.sh init /absolute/private/document-research-data
```

数据目录必须是绝对路径，位于源码仓库外，不能复用原平台的 `backend`、`outputs`、`workspaces`、`projects`。初始化只执行一次；已有配置不会被覆盖。生成的 `config.json` 权限为 `0600`，目录为 `0700`。

先保留自动生成的专用访问令牌。连接页面后点击“模型设置”，可填写 API 地址、模型名称、API 密钥和可选思考强度，无需手工编辑模型配置。保存不会调用模型；密钥不回显、不存入浏览器存储，留空保留已有密钥，勾选清除才删除。模型设置影响此独立服务的全部任务，只有配置管理员能访问。

新配置的 `settings_admins` 默认为 `["local"]`；旧配置没有此字段时也仅允许 `local`。多身份部署需由服务管理员在仓库外配置中显式添加有权限的身份名称。智谱检索密钥、知识库授权和身份令牌仍在服务端管理。若需要手工配置，格式如下；不要把文件、令牌或提供商密钥发到聊天或提交 Git：

```json
{
  "tokens": {"local": "保留初始化生成的随机令牌"},
  "settings_admins": ["local"],
  "model": {
    "base_url": "https://你的兼容服务/v1",
    "api_key": "通过前端模型设置保存，或仅填写在本机配置文件",
    "model": "该服务实际支持的模型标识"
  },
  "zhipu": {
    "api_key": "仅填写在本机配置文件",
    "libraries": {
      "local": [{"id": "实际已有知识库ID", "name": "软件研发资料"}]
    }
  }
}
```

如果本机联网必须经过代理，可在专用配置中显式添加 `"network": {"proxy_url": "http://127.0.0.1:你的代理端口"}`。不需要代理时省略该项或保持空值。服务不会自动读取环境代理；loopback 模型地址始终直连。代理属于数据发送路径，请只使用你信任的代理。

未使用的提供商字段保持空值。模型采用 OpenAI 兼容的 Chat Completions JSON 响应接口；具体提供商兼容性需要真实联调。智谱权限来自服务端用户到知识库 ID 的映射，前端不能自行填一个 ID 就越权访问。

使用智谱 `glm-5.3-flash` 时，模型地址填写 `https://open.bigmodel.cn/api/paas/v4`，并可在 `model` 对象内增加 `"reasoning_effort": "low"`。密钥必须填写真实值，不能保留示例说明文字。该型号始终开启思考，不接受 `thinking.type=disabled`；本入口可选透传 `reasoning_effort` 的 `low`、`high`、`max` 三个值，未设置时不添加该参数，其他模型需先确认兼容性。低档位用于先验证完整调用链，不能作为研究报告质量已达标的依据。模型与知识库按智谱各自规则计费；依据见[模型说明](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash.md)及[官方价格](https://docs.bigmodel.cn/cn/guide/start/pricing)。

启动服务：

```sh
DOCUMENT_RESEARCH_PYTHON=../document-research-venv/bin/python \
  sh scripts/document-research.sh start /absolute/private/document-research-data 4198
```

另开终端启动原 Vue 前端：

```sh
cd web
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1 --port 4196
```

打开 `http://127.0.0.1:4196/document-research`，输入配置中 `tokens.local` 的专用令牌。它只保存在该入口独立的浏览器会话存储中。平台原登录令牌不能替代它。

Vite 默认把专用 API 代理到 `http://127.0.0.1:4198`。如果开发服务器运行在另一个容器或受控主机，可通过仅供 Vite 使用的 `DOCUMENT_RESEARCH_PROXY_TARGET` 指定可达的专用服务地址；它不是浏览器中的模型地址。生产静态入口使用下面的可选覆盖层。

需要本机公网检索时，可单独启动 Open Websearch（不需要智谱配置）：

```sh
docker run -d --name document-research-websearch \
  -p 127.0.0.1:3210:3210 -e SEARCH_MODE=request \
  ghcr.io/aas-ee/open-web-search@sha256:748f1d083c9930db8e8b5f017834e1efa9ec77844dbed01baef2acf3ad47e81a \
  node build/index.js serve --host 0.0.0.0 --port 3210
```

已有可达的 Open Websearch 服务时直接在前端填写地址；浏览器地址与容器内地址不同，容器中 loopback 指该容器本身。公网搜索服务需要可用的互联网连接；代理如有需要应显式配置到搜索服务，不继承模型密钥。

## 可选 Docker 静态入口

原平台默认 Compose 仍保持原有服务和挂载。显式添加 `docker/document-research/compose.yaml`，才会启用专用容器、网络、数据卷及 Nginx 代理。需要支持 `!override` 的 Docker Compose。先按根 README 准备原平台的 `.env`，其中不要放专用资料服务的令牌或提供商密钥。

在仓库根目录定义本次操作的命令：

```sh
dr_compose() {
  docker compose --env-file .env \
    -f compose.yaml -f compose.local.yaml \
    -f docker/document-research/compose.yaml "$@"
}
dr_compose build document-research web
dr_compose run --rm --no-deps document-research init
```

初始化只对全新专用卷执行一次；再次执行会拒绝覆盖现有配置。随后启动专用服务和静态 Web：

```sh
dr_compose up -d --no-deps document-websearch document-research web
```

这条命令不会启动原平台 API、worker 或数据库。若要查看原 Agent 系统，需要另外按原平台文档启动其服务；仅启动这些专用服务和 Web 不能称为完整平台就绪。覆盖层将 Web 默认端口绑定到 `127.0.0.1:5173`（可通过 `DEEP_RESEARCH_WEB_PORT` 调整）；专用资料容器没有宿主机端口。打开 `http://127.0.0.1:5173/document-research`。

专用卷中的 `/var/lib/document-research/config.json` 不会输出到容器日志。模型可在页面“模型设置”中配置；需要读取令牌或配置智谱授权时，将配置复制到本机私有目录，用本机编辑器打开；不要提交或发到聊天：

```sh
umask 077
mkdir -p ../document-research-private
chmod 700 ../document-research-private
dr_compose cp document-research:/var/lib/document-research/config.json \
  ../document-research-private/config.json
chmod 600 ../document-research-private/config.json
```

保留原 `tokens` 映射，按前述配置格式填写模型和智谱字段。可用以下命令把本机编辑后的 JSON 原子写回专用卷，保持容器用户与文件权限，不重置数据库：

```sh
dr_compose exec -T document-research python -c '
import json, os, pathlib, sys
value = json.load(sys.stdin)
assert isinstance(value, dict) and isinstance(value.get("tokens"), dict)
os.umask(0o077)
p = pathlib.Path("/var/lib/document-research/config.json")
t = p.with_name("config.json.new")
t.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
t.chmod(0o600)
os.replace(t, p)
' < ../document-research-private/config.json
```

服务按请求重新读取配置。容器里的 `127.0.0.1` 指容器自身；外部模型或显式代理地址必须能从专用容器访问。不会自动继承原平台的环境代理或模型配置。

仅 Web 同时加入原平台网络和专用网络，原 API/worker 的挂载、环境和网络保持不变。专用代理清除 Cookie，不向浏览器转发 Set-Cookie，继续使用独立 Bearer 令牌。默认 Nginx 增加可选配置目录的空匹配 include；未启用覆盖层时不会要求资料服务存在。此配置没有开放公网访问。

停止资料及专用搜索服务用 `dr_compose stop document-research document-websearch`。撤销入口代理时，使用原 Compose 文件重建 Web；保留专用数据卷，避免使用 `down --volumes` 删除自己的资料。实际执行结果及未验证项见验收记录。

## 外发与来源

选择智谱库时，检索问题会发送给智谱；上传原文件不会自动同步到智谱。生成报告前还必须同意把该任务的问题和所选证据发送给已配置模型。

公开资料引用、本地提取文本与智谱切片分别标识。没有页码的来源不显示伪造页码；提供商错误与“没有匹配资料”不是同一种结果。模型只能引用提供的来源 ID，未知引用应导致任务失败而非进入报告。引用校验确认来源存在与非空引句匹配，不证明优缺点、因果关系或推荐理由已被证据充分支持；真实报告仍需研发人员复核。

标准智谱接口依据 [官方知识库检索文档](https://docs.bigmodel.cn/api-reference/知识库-api/知识库检索)：`POST /api/llm-application/open/knowledge/retrieve`，成功业务码为 `200`，结果在顶层 `data` 数组。它不是知识图谱 API，标准响应也不保证页码。真实账户权限、配额、引用字段质量需要单独联调。

## 验证和故障处理

合成软件样本位于 `validation/document-research/`。实际执行结果见 [本轮验收记录](DOCUMENT_RESEARCH_ACCEPTANCE.md)，工作日志中保留失败与修复，不将合成提供商测试当作真实模型或智谱验收。

- 401：专用令牌缺失、已更换或已撤销；重新从本机配置确认，不使用原平台 token。
- 403/404：任务选库、文档或任务不再授权；重新选择当前可见资料，不复用旧报告。
- 模型未配置：通过页面“模型设置”补齐地址、模型和密钥；不需重置平台数据库。403 表示该身份没有设置权限，需由服务管理员修改 `settings_admins`。
- 解析失败：按原因更换文本文件、解除 PDF 加密或先自行 OCR 后再上传；可以删除失败记录后重试。
- 提供商失败：保留错误状态，检查地址、权限和额度；不应当作空检索结果继续给出确定结论。

停止服务用对应终端的 Ctrl-C。卸载或回滚代码不会自动删除专用数据；先单独备份该目录，再按验收记录的回滚方法处理。
