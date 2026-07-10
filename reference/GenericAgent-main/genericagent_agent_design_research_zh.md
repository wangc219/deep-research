# GenericAgent Agent 设计调研报告

> 调研对象：`markdown_ga技术报告.md` 与当前仓库源码。  
> 重点：联网工具设计、memory 管理方式，以及与常见 agent 设计差异较大的亮点。  
> 日期：2026-06-08。

## 0. 一句话结论

GenericAgent 的核心不是“给 agent 加更多工具”，而是把 agent 运行过程视为一个上下文信息密度优化问题：工具越少越原子化，观察结果越压缩越语义化，memory 越按需加载越好，长期经验必须经过行动验证后再沉淀为 SOP 或脚本。这个设计让它在源码上非常小，但把复杂能力转移到了“工具组合 + memory 自演化 + CLI 可组合性”上。

## 1. 证据入口

建议先按这个顺序读：

1. `markdown_ga技术报告.md`
   - 总纲：contextual information density maximization。
   - 工具：2.1.1、2.3.1、附录 Table 10/11。
   - memory：2.1.2、2.3.2、4.3。
   - web：4.5、附录 Case A4。
2. `agent_loop.py`
   - 最小 agent loop，工具调度逻辑集中在 `agent_runner_loop()`。
3. `agentmain.py`
   - 系统 prompt、memory 初始化、任务队列、CLI/reflect/task 模式入口。
4. `ga.py`
   - 9 个工具的运行时实现，尤其是 `web_scan`、`web_execute_js`、`update_working_checkpoint`、`start_long_term_update`。
5. `TMWebDriver.py` + `simphtml.py` + `assets/tmwd_cdp_bridge/background.js`
   - 浏览器接管、简化 HTML、JS/CDP 执行与页面变化监控。
6. `memory/memory_management_sop.md`
   - L1/L2/L3/L4 的写入边界和“No Execution, No Memory”原则。

## 1.1 源码证据索引

| 主题 | 主要证据 |
|---|---|
| 最小 agent loop | `agent_loop.py:42` 的 `agent_runner_loop()`，`agent_loop.py:17` 的基础回调 |
| 工具 schema 加载 | `agentmain.py:17` 的 `load_tool_schema()`，`assets/tools_schema.json` |
| 系统 prompt + 默认 memory 注入 | `agentmain.py:39` 的 `get_system_prompt()`，`ga.py:584` 的 `get_global_memory()` |
| web 观察工具 | `ga.py:120` 的 `web_scan()`，`ga.py:322` 的 `do_web_scan()` |
| web 执行工具 | `ga.py:170` 的 `web_execute_js()`，`ga.py:337` 的 `do_web_execute_js()` |
| 浏览器桥 | `TMWebDriver.py:36` 的 `TMWebDriver`，`TMWebDriver.py:183` 的 `execute_js()` |
| 简化 DOM 与页面变化监控 | `simphtml.py:705` 的 `get_html()`，`simphtml.py:820` 的 `execute_js_rich()` |
| working checkpoint | `ga.py:442` 的 `do_update_working_checkpoint()`，`ga.py:540` 的 `_get_anchor_prompt()` |
| 每轮 summary 压缩 | `ga.py:552` 的 `turn_end_callback()` |
| 长期 memory 结算入口 | `ga.py:509` 的 `do_start_long_term_update()` |
| 历史压缩/淘汰 | `llmcore.py:40` 的 `compress_history_tags()`，`llmcore.py:97` 的 `trim_messages_history()` |
| 工具 schema elision | `llmcore.py:771` 的 `ToolClient`，`llmcore.py:800` 的 `_prepare_tool_instruction()` |
| native tool 适配 | `llmcore.py:1006` 的 `NativeToolClient` |
| reflect/scheduler | `reflect/scheduler.py:62` 的 `check()` |
| L4 会话归档 | `memory/L4_raw_sessions/compress_session.py:43` 的 `compress_session()`，`memory/L4_raw_sessions/compress_session.py:154` 的 `batch_process()` |
| 插件钩子 | `plugins/hooks.py:10`、`plugins/hooks.py:17`、`plugins/hooks.py:46` |

## 2. 总体架构

### 2.1 设计公理：上下文信息密度最大化

技术报告的主张是：长程 agent 的瓶颈不只是上下文长度，而是有限上下文中有多少“对下一步决策真正有用的信息”。因此 GA 同时追求：

- 完整性：当前决策必须知道的信息要在上下文里。
- 简洁性：无关历史、冗余工具描述、低价值网页 DOM、未经验证的记忆都不要常驻。
- 自然性：压缩后仍尽量保持模型可读。

源码对应关系：

- 工具 schema 极少：`assets/tools_schema.json` 只有 9 个工具。
- 默认 prompt 只注入 L1 memory 索引，而不注入完整 memory：`agentmain.py:get_system_prompt()` 调用 `get_global_memory()`。
- 每次工具调用后追加 working anchor：`ga.py:_get_anchor_prompt()`。
- 历史上下文会做标签压缩和 FIFO 淘汰：`llmcore.py:compress_history_tags()`、`trim_messages_history()`。

### 2.2 最小 agent loop

`agent_loop.py:agent_runner_loop()` 做的事情很少：

1. 构造 system/user 消息。
2. 调 LLM。
3. 解析 tool calls。
4. 根据工具名分发到 handler 的 `do_<tool_name>()`。
5. 将工具结果和下一轮 prompt 回灌。
6. 没有工具调用时触发 `do_no_tool`，把它当成结束或异常情况处理。

值得注意的是，loop 自己不内置“浏览器 agent”“文件 agent”“memory agent”等复杂子系统；复杂性主要在工具实现、prompt policy 和 memory 文件中。

## 3. 联网工具设计

### 3.1 对外只暴露两个 web 原子工具

GA 的 web 工具只有：

- `web_scan`：读取当前浏览器标签页，返回标签列表和简化后的 HTML/文本。
- `web_execute_js`：在当前或指定标签页执行 JS，必要时走 CDP 桥，完成点击、输入、导航、读取、cookie/CDP 操作等。

这与常见 agent 的差异很大。很多 WebAgent 会暴露 `navigate`、`click`、`type`、`search`、`extract`、`screenshot`、`wait` 等多个动作；GA 则把网页动作折叠成“观察”和“执行 JS”两个原子能力。复杂网页任务靠模型生成 JS 组合完成。

技术报告把这归入 minimal atomic toolset：web reading 对应 `web_scan`，web interaction 对应 `web_execute_js`。附录 Table 11 还明确说 WebFetch/WebSearch 可以由 `web_scan + web_execute_js + code_run` 组合替代。

### 3.2 它接管真实用户浏览器，而不是启动独立沙箱

`memory/tmwebdriver_sop.md` 明确写道：底层通过 Chrome 扩展接管用户浏览器，非 Selenium/Playwright，保留登录态和 Cookie。

源码路径：

- `TMWebDriver.py`：本地启动 WS 服务和 HTTP long-poll 服务，维护 tab session。
- `assets/tmwd_cdp_bridge/background.js`：Chrome 扩展侧连接本地 WS，接收执行请求。
- `ga.py:first_init_driver()`：第一次使用 web 工具时初始化 `TMWebDriver()`。

优点：

- 能使用用户现有登录态，适合真实网页自动化。
- 避免每次重新登录或迁移 Cookie。
- 可以操作真实 Chrome 标签页，跨平台站点和复杂前端更接近人工浏览。

代价：

- 依赖本地浏览器扩展安装和连接状态。
- JS 事件可能 `isTrusted=false`，敏感操作需要 CDP 或物理输入兜底。
- 安全边界更依赖 prompt/权限策略，而不是沙箱隔离。

### 3.3 `web_scan` 的关键不是“返回 HTML”，而是压缩观察

`web_scan` 在 `ga.py` 中调用 `simphtml.get_html(driver, cutlist=True, maxchars=...)`。`simphtml.py` 里做了几类压缩：

- 删除低价值标签：script/style/meta/link 等。
- 过滤隐藏、浮动、不可见元素。
- 保留输入框值、checkbox/radio 状态、select 当前值。
- 尝试穿透同源 iframe 和 shadowRoot。
- 对主体列表做 cutlist：长列表只保留少量样本，插入 `[FAKE ELEMENT] ... more items hidden` 提示。
- 超长 DOM 走 `smart_truncate()`，按 DOM 子树预算递归截断，而不是简单从字符串中间砍。
- `text_only=true` 时只返回规整文本和表单提示。

这对应技术报告 4.5 的核心观点：web 环境里 raw HTML/DOM 容易压垮上下文，GA 的优势来自“结构化浏览器抽取 + 压缩后的观察”。

### 3.4 `web_execute_js` 兼具动作、读取和 CDP 桥入口

`ga.py:do_web_execute_js()` 支持：

- 从参数或回复里的 JavaScript code block 提取脚本。
- 如果 `script` 是本地文件路径，则读取文件作为 JS。
- 可指定 `switch_tab_id`。
- 可用 `save_to_file` 保存长 JS 返回值，只把短 preview 放进上下文。
- 单次工具多调用时按 `_tool_num` 分摊最大返回长度。

`simphtml.execute_js_rich()` 在执行动作前后会做页面变化监控：

- 执行前抓取 baseline HTML。
- 执行 JS。
- 检测新标签页。
- 读取短暂出现的 transient 文本。
- 对执行前后的 DOM 做 diff，返回变化量和最显著变化。

这使得一次 JS 动作不仅是“执行”，还会给模型一个行动反馈闭环：动作是否成功、页面是否刷新、是否有新 tab、DOM 哪块变化。

### 3.5 CDP 扩展桥是 web 工具的高级兜底

`assets/tmwd_cdp_bridge/background.js` 支持：

- `cookies`
- `tabs`
- `cdp`
- `batch`
- `management`
- `contentSettings`

并且有一个关键 fallback：普通 `chrome.scripting.executeScript` 因 CSP 或上下文问题失败时，会尝试通过 `chrome.debugger` 的 `Runtime.evaluate` 执行。

`tmwebdriver_sop.md` 还记录了很多真实网页自动化坑点：

- JS 点击可能被 `isTrusted=false` 拦截。
- 文件上传首选 DataTransfer API，必要时 CDP。
- 自定义下拉框可用 CDP 三事件点击。
- 跨域 iframe 可用 CDP frame tree + isolated world。
- Chrome autofill 保护值需要前台 tab + CDP/物理点击释放。

这说明 GA 的联网能力不是靠一个复杂浏览器框架，而是靠一套“简化观察 + JS 优先 + CDP 兜底 + SOP 记坑”的组合。

### 3.6 Web 设计思想总结

GA web 层的设计可以概括为：

```text
真实浏览器登录态
  -> web_scan 低成本观察
  -> 模型生成 JS 精确操作
  -> execute_js_rich 监控页面变化
  -> 复杂受限场景走 CDP 桥
  -> 成功经验写入 tmwebdriver_sop 等 L3 SOP
```

它和现有 agent 的主要区别：

- 不把浏览器动作枚举成很多工具，而是把动作统一为 JS。
- 不把网页完整塞进上下文，而是主动提炼 DOM。
- 不追求框架内置全部 web 技巧，而是把特殊站点/特殊控件经验沉淀到 SOP。
- 使用用户真实浏览器环境，能力上限高，但安全/稳定性更依赖本地配置和 SOP 约束。

## 3.7 CloakBrowser 与 GA 联网工具结合调研

### 3.7.1 CloakBrowser 是什么

CloakBrowser 项目地址：`https://github.com/CloakHQ/cloakbrowser`。从公开 README 看，它的定位是 “A browser built for agents”，核心形态是：

- 自定义 Chromium 二进制。
- Python 包装器：`CloakBrowser`、`CloakPlaywright`。
- Node/TS 包装器：`CloakBrowser`、`CloakPuppeteer`。
- 可通过 CDP endpoint 连接。
- 支持 persistent profile。
- 支持 proxy、geoip、humanize 等选项。
- 官方强调与 Playwright、Puppeteer、Stagehand、Browser Use 等 agent/browser 框架集成。

本节对 CloakBrowser 的判断主要来自该仓库 README、项目文档入口和二进制许可说明；对 GA 结合点的判断来自本仓库 `ga.py`、`TMWebDriver.py`、`simphtml.py`、`memory/tmwebdriver_sop.md`。

它与 GA 当前 `TMWebDriver` 的根本差异：

| 维度 | GA 当前 TMWebDriver | CloakBrowser |
|---|---|---|
| 浏览器来源 | 用户现有 Chrome + 扩展桥 | 自定义 Chromium 二进制 |
| 登录态 | 天然使用用户当前浏览器登录态 | 通过 persistent profile 维护 |
| 控制接口 | GA 自研 WS/HTTP + Chrome 扩展 + JS/CDP | Playwright/Puppeteer/CDP |
| 反检测能力 | 主要依赖真实浏览器环境和人工式操作 SOP | 项目目标之一就是更接近真实浏览器指纹/行为 |
| 与 GA 工具契合度 | 已完全契合 `web_scan/web_execute_js` | 需要适配 driver 接口 |

### 3.7.2 能力互补点

GA 当前 web 工具的强项是“真实用户浏览器状态”：

- 可直接使用用户已经登录的站点。
- 能操作用户当前打开的 tab。
- `web_scan` 的 DOM 压缩已经很适合 agent 上下文。
- `web_execute_js` + CDP 桥可以处理很多复杂页面。

CloakBrowser 的强项是“自动化浏览器环境更不容易被识别为自动化”：

- 自定义 Chromium 能从更底层处理 webdriver/指纹差异。
- Playwright/Puppeteer 生态成熟，动作模型和等待机制完整。
- persistent profile 可隔离站点状态。
- proxy/geoip/humanize 更适合批量、公开网页、搜索、采集、评测任务。

因此最合理的结合不是替换，而是形成双后端：

```text
GA web_scan / web_execute_js
  -> BrowserDriver 抽象层
      -> TMWebDriverBackend：接管用户 Chrome，适合登录态/个人网页任务
      -> CloakBrowserBackend：启动 Cloak Chromium，适合公开网页/高反自动化/隔离任务
```

### 3.7.3 三种可行结合方案

#### 方案 A：把 CloakBrowser 当外部辅助工具，由 `code_run` 调用

做法：

- 不改 GA 核心 web 工具。
- 在 L3 新增 `cloakbrowser_sop.md`。
- 需要时通过 `code_run` 执行 Python/Node 脚本：
  - 启动 CloakBrowser。
  - 用 Playwright/Puppeteer 打开网页。
  - 提取文本/HTML/截图。
  - 将结果写文件，再由 `file_read` 读回。

优点：

- 实现最快，几乎不动 GA。
- 不破坏 `web_scan/web_execute_js` 的最小工具设计。
- 适合先做 proof-of-concept。

缺点：

- Agent 不能直接复用 GA 的 `simphtml.get_html()` 压缩观察，除非脚本主动调用。
- 每次任务需要模型临时组织脚本，操作链更长。
- 交互式点击/多轮状态管理不如内置 driver 顺畅。

适合：先验证 CloakBrowser 是否在目标站点上确实比当前 Chrome 扩展桥更稳定。

#### 方案 B：新增 CloakBrowser driver backend，但保持 GA 对外两个 web 工具不变

做法：

- 新增一个 driver 类，例如 `CloakWebDriver`。
- 它实现与 `TMWebDriver` 尽量一致的最小接口：
  - `get_all_sessions()`
  - `get_session_dict()`
  - `execute_js(code, timeout=..., session_id=...)`
  - `default_session_id`
- `ga.py:first_init_driver()` 根据配置选择：
  - 默认 `TMWebDriver`
  - 设置环境变量或 mykey 配置后使用 `CloakWebDriver`
- `simphtml.get_html()` 继续通过 `driver.execute_js()` 运行页面内 JS，所以可以复用 DOM 压缩逻辑。

优点：

- 对模型透明，仍只看到 `web_scan` / `web_execute_js`。
- 保留 GA 的信息密度优势。
- 后端切换不扩大工具 schema。
- 适合长期维护。

缺点：

- 需要处理 CloakBrowser 的生命周期：安装、启动、关闭、profile 路径、端口、异常恢复。
- Playwright/Puppeteer 的 page/session 概念要映射到 GA 的 tab session。
- `execute_js_rich()` 的页面变化监控能复用，但新 tab 检测、reload 检测要适配。

这是推荐方案。

#### 方案 C：新增专用工具，如 `web_stealth_scan` / `web_stealth_execute`

做法：

- 在 `assets/tools_schema.json` 新增工具。
- 专门暴露 CloakBrowser 能力。

优点：

- 模型可显式选择“普通浏览器”还是“隐身/隔离浏览器”。
- 工具描述可以直接提示使用边界。

缺点：

- 违背 GA 最小工具集原则。
- 工具 schema 增大，动作空间变复杂。
- 容易让模型在不需要时滥用 stealth browser。

不建议作为第一阶段方案。除非后续证明双后端切换需要模型参与决策，否则应避免新增对外工具。

### 3.7.4 推荐设计

推荐分两阶段：

**第一阶段：SOP + 外部脚本验证。**

- 新增 `memory/cloakbrowser_sop.md`，只写安装、启动、适用场景和风险。
- 用 `code_run` 跑一个最小脚本验证：
  - 打开公开网页。
  - 获取 title/body text。
  - 执行一次点击或搜索。
  - 输出 HTML/text 到文件。
- 不改 GA 核心源码。

**第二阶段：driver backend 集成。**

- 新建 `CloakWebDriver.py`。
- 让它实现 `TMWebDriver` 的最小兼容接口。
- 在 `ga.py:first_init_driver()` 加配置选择，而不是新增 web 工具。
- 复用 `simphtml.get_html()` 和 `simphtml.execute_js_rich()`。
- 在 `memory/tmwebdriver_sop.md` 或新 SOP 中记录：
  - TMWebDriver 用于用户真实登录态。
  - CloakBrowser 用于公开网页、隔离 profile、反自动化误报较高的网站。

### 3.7.5 可能实现方式

一个可维护的 `CloakWebDriver` 需要做到：

```python
class CloakWebDriver:
    def __init__(self, profile_dir=None, headless=False, proxy=None):
        ...

    def get_all_sessions(self):
        return [{"id": "...", "url": "...", "title": "...", "type": "cloak"}]

    def get_session_dict(self):
        return {session["id"]: session["url"] for session in self.get_all_sessions()}

    def execute_js(self, code, timeout=15, session_id=None):
        # 在对应 page 上 evaluate JS
        # 返回格式尽量对齐 TMWebDriver: {"data": result}
        ...
```

如果使用 Playwright backend，`execute_js` 可大致映射为 `page.evaluate()`。如果使用 CDP endpoint，GA 也可以保留 CDP 风格操作能力，但建议先通过 Playwright 封装完成最小可用版本。

### 3.7.6 可行性评估

总体可行，原因是 GA 的 web 层已经把对浏览器后端的依赖压缩得很薄：

- `ga.py:web_scan()` 只要求 driver 能列 tab、切默认 session、执行 JS。
- `simphtml.get_html()` 只要求 driver 能在页面里运行 JS 并返回数据。
- `simphtml.execute_js_rich()` 只要求 driver 执行 JS 后返回结果，并能列 session 检测新 tab。

主要工作量不是改 agent loop，而是做浏览器生命周期和接口兼容。按风险估计：

- POC：0.5-1 天。
- 最小 driver backend：1-3 天。
- 稳定支持多 tab、profile、proxy、异常恢复、安装检测：3-7 天。
- 和现有 SOP/memory 体系长期磨合：持续迭代。

### 3.7.7 主要弊端与风险

1. 合规与网站条款风险  
   CloakBrowser 的目标能力容易被理解为绕过机器检测。即使技术上可行，也应限制在用户授权、公开信息、低频、遵守 robots/ToS 或内部测试场景。不能把它作为批量滥采、撞库、绕过访问控制的工具。

2. 安全边界更复杂  
   GA 已经能执行代码和控制浏览器；再接入更强的自动化浏览器后，错误脚本、恶意网页、cookie/profile 泄露风险更高。Cloak profile 应与用户日常 Chrome profile 隔离。

3. 维护成本上升  
   自定义 Chromium 二进制、Playwright/Puppeteer 版本、操作系统差异、代理设置都会带来安装和升级问题。

4. 与 GA 当前优势部分冲突  
   GA 当前 TMWebDriver 最大优势是“真实用户浏览器登录态”。CloakBrowser 如果用独立 profile，就不能天然复用用户当前登录态；如果导入 Cookie，又会引入隐私和安全问题。

5. 反检测不是可靠保证  
   网站检测会持续变化。CloakBrowser 能降低自动化误报，不应被当成“保证通过”的能力。集成后仍要保留失败升级、ask_user、人工验证等 GA 原有机制。

6. 可能增加上下文和工具复杂度  
   如果为了 CloakBrowser 新增很多工具，会破坏 GA 的最小工具哲学。因此建议只在 driver 层集成，保持对模型暴露的 web 工具不变。

### 3.7.8 最终判断

可以结合，而且最合理的结合方式是“可选浏览器后端”，不是新增一堆 stealth 工具。

推荐优先级：

1. 先用 `code_run` + CloakBrowser 做目标站点 POC，验证收益。
2. 若收益明确，再实现 `CloakWebDriver`，保持 `web_scan/web_execute_js` 不变。
3. 默认仍使用 `TMWebDriver`；只有公开网页、隔离任务、反自动化误报明显时切换 CloakBrowser。
4. 把使用边界写入 L3 SOP，并在 L1 加一个极短存在性指针，例如 `cloakbrowser_sop(公开网页/反检测误报)`。

## 4. Memory 管理方式

### 4.1 四层 memory

技术报告和 `memory/memory_management_sop.md` 对 memory 的分层一致：

| 层级 | 文件/目录 | 作用 | 是否默认进上下文 |
|---|---|---|---|
| L0 | `memory/memory_management_sop.md` | memory 写入规则、红线、分类树 | 不默认注入，需要写 memory 前读取 |
| L1 | `memory/global_mem_insight.txt` | 极简索引、场景触发词、高 ROI 规则 | 默认注入 |
| L2 | `memory/global_mem.txt` | 长期稳定事实，如路径、配置、用户偏好 | 按需读取 |
| L3 | `memory/*.md` / `memory/*.py` | 任务 SOP、可复用脚本、特定坑点 | 按需读取 |
| L4 | `memory/L4_raw_sessions/` | 原始会话压缩归档、可追溯历史 | 极少直接注入 |

当前克隆仓库还没有运行时生成的 `memory/global_mem.txt` 和 `memory/global_mem_insight.txt`；`agentmain.py` 启动时会创建它们，L1 从 `assets/global_mem_insight_template.txt` 初始化。

### 4.2 L1 的本质是“存在性编码”

`memory/memory_cleanup_sop.md` 对 L1 的解释很重要：LLM 本身是压缩器和解码器，L1 只需要让模型意识到“某类知识存在”，它就会通过 tool call 自己去读下层内容。

因此 L1 不写教程，只写：

- 场景关键词 -> SOP/脚本/事实位置。
- 不提醒就容易犯的高 ROI 规则。
- 反直觉触发词。

模板例子 `assets/global_mem_insight_template.txt`：

- `浏览器特殊操作: tmwebdriver_sop(文件上传/图搜/PDF blob/物理坐标/HttpOnly Cookie/autofill突破/跨域iframe/CDP/跨tab)`
- `定时: scheduled_task_sop`
- `手机: adb_ui.py`

这不是知识正文，而是 routing map。

### 4.3 长期 memory 的写入原则：No Execution, No Memory

`memory/memory_management_sop.md` 的最高优先级规则是：

- 写入 L1/L2/L3 的信息必须来自成功工具调用结果。
- 禁止把模型推理、固有知识、未验证计划写成事实。
- 禁止存储易变状态。
- 上层只留最小充分指针。

这和许多“自动总结对话即 memory”的系统不同。GA 把 memory 当作有污染风险的长期资产，而不是日志池。没有行动验证就不写入。

### 4.4 Working memory：每轮自动注入的短期锚点

长期 memory 之外，GA 还有一个当前任务内的 working checkpoint：

- 工具 schema 中 `update_working_checkpoint` 描述它是短期工作记事板。
- `ga.py:do_update_working_checkpoint()` 把 `key_info` 和 `related_sop` 存到 handler 的 `self.working`。
- `ga.py:_get_anchor_prompt()` 在每次工具调用后生成 `[WORKING MEMORY]`，包含：
  - 最近约 30 条一行摘要。
  - 更早摘要折叠后的 earlier_context。
  - 当前 turn。
  - `key_info`。
  - 相关 SOP 提醒。

技术报告说 anchor 每次工具调用后自动附到下一条 user message，用于在历史被压缩或淘汰后仍保留任务关键状态。源码里确实是在多数工具返回时把 `_get_anchor_prompt()` 作为 `next_prompt`。

### 4.5 `<summary>` 是 working history 的压缩单元

`llmcore.py` 的文本协议要求每次回复先输出 `<summary>`，且少于 30 字/词。`ga.py:turn_end_callback()` 会提取 `<summary>`，追加到 `history_info`：

```text
[Agent] <summary 内容>
```

如果模型没给 summary，handler 会用工具名和参数生成兜底摘要，并在下一轮提示必须包含 `<summary>`。

这个机制很关键：GA 没有把完整推理过程长期挂在上下文里，而是把每轮压成一行“物理快照”，再由 working anchor 滚动携带。

### 4.6 长期更新不是立即写，而是触发结算

`start_long_term_update` 不是直接把内容写入 memory。`ga.py:do_start_long_term_update()` 的行为是：

1. 生成一个“总结提炼经验”的下一轮 prompt。
2. 注入当前 global memory。
3. 读取 `memory/memory_management_sop.md` 作为 L0。
4. 要求模型判断是否有经验证、未来可复用的信息。
5. 如果有，按规则用 `file_read` + `file_patch` 做最小更新。

这相当于两阶段提交：

```text
发现可能值得记忆的信息
  -> start_long_term_update 进入结算流程
  -> 读取 L0 规则
  -> 验证分类
  -> 最小 patch L2/L3
  -> 必要时同步 L1 指针
```

好处是避免每轮都污染长期 memory；坏处是依赖模型遵守 memory SOP，仍不是硬编码数据库事务。

### 4.7 L4 原始会话归档

`reflect/scheduler.py` 每 12 小时尝试运行 `memory/L4_raw_sessions/compress_session.py`，把 `temp/model_responses` 中较老的模型交互日志压缩归档。

`compress_session.py` 做几件事：

- 从 `model_responses_*.txt` 解析 Prompt/Response 时间戳。
- 对 raw 格式去掉系统 prompt 和 assistant echo。
- 提取 `<history>` 中的 `[USER]` / `[Agent]` 摘要。
- 将 history 追加到 `all_histories.txt`。
- 将压缩会话按月份打包 zip。
- 删除已归档 raw 文件。

因此 L4 更像“可追溯会话档案”和“后续 salient mining 的材料”，不是默认检索库。

### 4.8 Memory 设计思想总结

GA memory 的核心不是向量检索，而是分层、指针化和验证准入：

```text
L1 极简存在性索引常驻
  -> L2/L3 按需读取
  -> working checkpoint 承载当前任务关键状态
  -> summary 压缩每轮轨迹
  -> L4 保存原始历史以备审计/挖掘
  -> 长期 memory 只接受行动验证后的最小补丁
```

它和常见 memory agent 的差异：

- 不默认使用 embedding/vector DB。
- 不把对话总结直接当长期记忆。
- 不追求“记得更多”，而是“默认上下文更少，但知道去哪里取”。
- 对 memory 污染非常敏感，强调 verified data 和 patch-only。

## 5. 上下文管理与模型适配

### 5.1 历史压缩

`llmcore.py:compress_history_tags()` 定期压缩旧消息里的：

- `<thinking>`
- `<think>`
- `<tool_use>`
- `<tool_result>`
- `<history>`
- `<key_info>`
- `<earlier_context>`

其中 `<history>` / `<key_info>` 旧副本会被替换为占位，避免 working anchor 的多份旧版本重复占用上下文。

`trim_messages_history()` 用 `context_win * 3` 的字符预算近似 token 预算；超过后先压缩，再按 FIFO 删除旧消息，保留到约 60% 预算。

### 5.2 工具 schema elision

技术报告提到 text-protocol path 会省略重复工具 schema。源码对应 `llmcore.py:ToolClient._prepare_tool_instruction()`：

- 如果工具 schema 和上一轮一致，只发送“工具库持续有效，协议沿用”的短提示。
- 每 10 轮 `agent_loop.py` 会重置 `client.last_tools`，重新发送完整工具描述。
- 如果累计上下文过长，也会重置。

这对非 native tool 模型尤其重要，因为工具 schema 本身会占很多 token。

### 5.3 Native tool 与文本协议双轨

GA 支持两类 LLM 后端：

- `NativeToolClient`：走模型原生 tool calling，如 Claude/OAI native。
- `ToolClient`：把工具调用协议写进文本 prompt，解析 `<tool_use>` XML/JSON。

`llmcore.py` 还做了 OpenAI/Claude message format 互转、tool schema 转换、SSE 解析、thinking block 修复、prompt caching 标记等。也就是说 GA 的核心 loop 不依赖单一模型 API。

### 5.4 MixinSession fallback

`MixinSession` 支持多个 session 后端失败切换，并在一段时间后 spring back 到主后端。这个设计不是 agent 核心理论的一部分，但对长程任务稳定性有实际意义：模型 API 出错不必立即中断整个任务。

## 6. 自演化与组合能力

### 6.1 自演化目标是策略和资产，不是工具接口

技术报告强调“what evolves: strategy, not tools”。源码也能看到工具 schema 固定在 9 个工具；新能力主要写进：

- L3 SOP：例如 `tmwebdriver_sop.md`、`scheduled_task_sop.md`、`autonomous_operation_sop.md`。
- L3 脚本：例如 `adb_ui.py`、`ui_detect.py`、`procmem_scanner.py`。
- 任务报告和历史档案。

这和“动态注册很多新工具”的系统不同。GA 用 `code_run` 写脚本、验证脚本，再通过 memory 让模型未来知道有这个脚本可用。

### 6.2 CLI 是组合能力的基础

`agentmain.py` 支持：

- 交互 CLI。
- `--task IODIR`：文件 IO 一次性任务模式，可后台启动。
- `--reflect SCRIPT`：反射模式，定期执行脚本里的 `check()`，有任务字符串就投入 agent。

因此 subagent、scheduled task、watchdog、autonomous operation 都可以用“外部脚本生成 prompt -> CLI/任务队列执行”组合出来，而不是改核心 loop。

### 6.3 定时和反射

`reflect/scheduler.py` 是一个典型 reflect script：

- 扫描 `sche_tasks/*.json`。
- 判断 schedule/repeat/cooldown/max_delay。
- 生成任务 prompt 和报告路径。
- 同时每 12 小时触发 L4 会话归档。

这体现了 GA 的设计取向：触发逻辑留在普通 Python 脚本里，执行逻辑仍由同一个 agent loop 处理。

### 6.4 自主行动 SOP

`memory/autonomous_operation_sop.md` 规定了无人值守时的边界：

- 先更新 working checkpoint。
- 查看历史和 TODO。
- 一次只选一条任务。
- 在临时目录实验。
- 即使失败也写报告。
- 修改 memory/安装软件/外部 API/删除非临时文件需要待用户审查。

这不是强制安全沙箱，但它把“自主探索”的行为边界显式写进 L3 SOP，使 agent 在无人值守时仍有可读、可修改的策略文件。

## 7. 与现有 agent 区别较大的亮点

### 7.1 小工具集反而提升能力密度

GA 的 9 工具不是能力少，而是把能力压缩成最小可组合原子：

- 文件读写改。
- 代码执行。
- 浏览器观察/JS 执行。
- 短期/长期 memory。
- 用户询问。

很多 specialized tools 可以由这些组合重建。优势是 prompt 常驻工具描述少，模型动作空间小，经验也更容易沉淀成“如何组合原子工具”的 SOP。

### 7.2 web 自动化靠真实浏览器 + JS/CDP，而不是工具枚举

这是本项目最有辨识度的工程点之一。它把浏览器动作上升为“在真实浏览器里执行程序”，因此：

- 搜索、点击、填写、抓取、下载、Cookie、CDP 都能通过同一个 `web_execute_js` 入口扩展。
- 页面观察则通过 `web_scan` 控制上下文成本。
- 特殊网页坑点通过 SOP 记忆演化。

### 7.3 Memory 是“路由系统”，不是“全文知识库”

L1 的存在性编码很值得学习。它不试图把知识都塞进 prompt，而是让模型知道：

- 有哪些能力。
- 什么时候该去读哪个 SOP。
- 哪些全局规则高风险。

这比“把所有历史摘要拼进 prompt”更接近可长期增长的 memory 设计。

### 7.4 Summary + working anchor 是轻量状态机

每轮 `<summary>` 加上 `_get_anchor_prompt()`，构成了一个非常轻量的任务状态机：

- 近期行为被压成一行摘要。
- 早期行为被折叠。
- 关键状态放在 key_info。
- 相关 SOP 名保留为指针。

它没有复杂 planner state 数据结构，但能在长任务里防止“忘了当前做到哪”。

### 7.5 自演化从自然语言 SOP 走向脚本

报告里的 LangChain PR case 展示了一个阶段变化：

```text
首次探索
  -> 文本 SOP
  -> SOP 优化
  -> Python 脚本
  -> 后续低成本执行
```

源码里这通过 `code_run`、`file_write/file_patch` 和 L3 memory 实现，而不是通过修改模型参数。

### 7.6 核心 loop 小到 agent 自己可理解

README 和报告都强调核心代码很小。这个亮点不只是代码美学：如果核心足够小，agent 未来有可能读取、理解、修改自身局部架构。大型 agent 框架往往难以做到这一点。

### 7.7 插件钩子极轻量

`plugins/hooks.py` 只是一个事件注册表，`agent_loop.py` 在 `agent_before`、`turn_before`、`llm_before`、`tool_before`、`tool_after` 等点触发。它没有复杂 plugin runtime，但足以插入 tracing、监控或策略补丁。

## 8. 风险与局限

1. 安全边界偏软  
   GA 能执行代码、写文件、控制真实浏览器，能力强但风险也高。很多边界依赖 prompt/SOP，而不是强制权限系统。

2. Memory 写入依赖模型自律  
   L0 规则很严，但最终仍是模型决定何时调用 `start_long_term_update`、如何 patch memory。没有数据库级事务和事实验证器。

3. Web 工具依赖本地 Chrome 扩展  
   如果扩展没连上、CSP/CDP 权限不稳定、tab 状态异常，web 工具会退化。SOP 能降低坑，但不能消除环境依赖。

4. 无 embedding 检索的代价  
   L1/L2/L3 的路由非常省 token，但在 memory 规模极大且命名混乱时，可能需要额外索引整理或搜索工具辅助。

5. 评测结论要区分论文主张和源码事实  
   技术报告中的 benchmark 数字是论文评测结论；源码能验证机制存在，但不能单独证明这些指标在任意环境复现。

## 9. 学习路线建议

如果你想学习并复现它的设计思想，建议按以下顺序动手：

1. 先读 `assets/tools_schema.json`，理解 9 工具边界。
2. 读 `agent_loop.py`，画出 LLM -> tool -> result -> next_prompt 的循环。
3. 读 `ga.py` 的 `GenericAgentHandler`，看每个工具如何返回 `StepOutcome`。
4. 重点调试 `web_scan`：
   - 跟到 `simphtml.get_html()`。
   - 看它如何压缩 DOM。
   - 对比 raw DOM 与简化 DOM。
5. 重点调试 `web_execute_js`：
   - 跟到 `TMWebDriver.execute_js()`。
   - 再看 `background.js` 如何执行普通 JS 和 CDP fallback。
6. 读 `memory_management_sop.md` 和 `memory_cleanup_sop.md`，理解为什么 L1 只写指针。
7. 在一个小任务中手动模拟：
   - 成功执行若干工具。
   - 调用 `update_working_checkpoint` 保存关键状态。
   - 完成后触发 `start_long_term_update`。
   - 按 L0 规则判断是否应写 L2/L3。
8. 最后读 `reflect/scheduler.py`，理解 CLI/reflect 如何把 agent 变成长程后台执行器。

## 10. 总结

GenericAgent 值得学习的不是某个单独模块，而是几个模块的同构设计目标：

- 工具层：少而原子，降低动作空间和 prompt overhead。
- Web 层：观察压缩，动作统一为 JS/CDP，保留真实浏览器状态。
- Memory 层：默认只注入索引，深层按需读取，长期写入必须验证。
- Context 层：summary、working anchor、标签压缩、消息淘汰共同控制有效上下文。
- 自演化层：把成功经验从轨迹压缩成 SOP，再从 SOP 固化成脚本。
- 架构层：CLI 是统一执行面，subagent/reflect/schedule/autonomous 都从同一 primitive 组合出来。

如果用一句工程化评价概括：GA 是一个“把能力做在组合和记忆里，而不是做在庞大框架里”的 agent。
