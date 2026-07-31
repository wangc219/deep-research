<!-- ppt-master-schema: design-spec/v1 -->
# 市场需求发散要求落实与评测汇报 - Design Spec

## I. Project Information

| Item | Value |
| --- | --- |
| Project Name | 市场需求发散要求落实与评测汇报 |
| Canvas Format | PPT 16:9, 1280 × 720 |
| Page Count | 23 |
| Target Audience | 项目管理层、业务需求方与技术评审人员 |
| Communication Intent | 先汇报发散需求的项目落实情况，再解释 Benchmark 与消融实验设计和结果，最后暴露证据质量与效率短板并推动下一阶段工作 |
| Desired Audience Outcome | 同意启动证据质量专项、50 条全量 Benchmark 和同版本消融复测 |
| Core Message / Ask / Action | 三层九项、制胜机理与评测闭环已落地且初步有效；下一阶段优先补强证据绑定、扩大样本并降低时延 |
| Delivery Context | 15–20 分钟现场汇报，兼顾会后阅读 |
| Artifact Afterlife | 作为阶段评审材料，后续可替换数据继续复测和复盘 |
| Reading Mode | balanced |
| Content Strategy | 结论先行；需求落实、评测证据、短板与行动逐层展开 |
| Design Style | 简单商务汇报风格，Swiss Minimal，白底、深蓝主色、绿色正向信号、少量橙色风险提示 |
| Formula Policy | text-only |
| AI Image Acquisition Path | not applicable；仅使用用户项目中的真实前端截图 |
| Generation Mode | continuous |
| Spec Refinement | disabled |
| Created Date | 2026-07-29 |

## II. Canvas Specification

| Property | Value |
| --- | --- |
| Format | PPT 16:9 |
| Dimensions | 1280 × 720 |
| viewBox | `0 0 1280 720` |
| Margins | 64 px horizontal, 46 px vertical safe margin |
| Content Area | x=64–1216, y=46–674 |

## III. Visual Theme

### Theme Style

- **Mode**: pyramid
- **Visual style**: swiss-minimal
- **Theme**: 研究评测与项目落实的可信商务汇报
- **Tone**: 克制、清晰、证据导向、结论先行

### Color Scheme

| Role | HEX | Purpose |
| --- | --- | --- |
| Background | #FFFFFF | 主背景与大面积留白 |
| Secondary background | #F3F6F9 | 卡片、表格和截图承托区 |
| Primary | #173B5E | 标题、关键结构与深色文本 |
| Accent | #2F6FAE | 主数据、流程和高亮信号 |
| Secondary accent | #2E8B66 | 已完成、胜出与推荐动作 |
| Body text | #1D2733 | 正文与图表标签 |
| Risk | #C97A32 | 风险、证据短板与警示 |
| Muted | #6B7785 | 注释、来源与次要标签 |

## IV. Typography System

### Font Plan

| Role | Chinese | English | Fallback tail |
| --- | --- | --- | --- |
| Title | PingFang SC | Arial | Microsoft YaHei, sans-serif |
| Body | PingFang SC | Arial | Microsoft YaHei, sans-serif |
| Data | Arial | Arial | PingFang SC, sans-serif |

- **Title stack**: PingFang SC, Arial, Microsoft YaHei, sans-serif
- **Body stack**: PingFang SC, Arial, Microsoft YaHei, sans-serif
- **Data stack**: Arial, PingFang SC, Microsoft YaHei, sans-serif
- **Role rationale**: 中文商务汇报优先使用系统稳定的苹方；数据使用 Arial 以获得紧凑清晰的数字形态。

### Font Size Hierarchy

| Purpose | Anchor Size (px) |
| --- | ---: |
| Body | 24 |
| Title | 42 |
| Subtitle | 32 |
| Annotation | 18 |
| Data | 30 |
| Hero | 66 |

## V. Layout Principles

### Page Structure

- **Header area**: 左上标题与短结论，右上可放页码或阶段标签；标题下使用一条短蓝色标尺线。
- **Content area**: 优先采用两栏、三栏或一张主图加证据侧栏；数据页保留充足坐标与标签空间。
- **Footer area**: 左侧放来源或口径，右侧放页码；不使用大面积装饰。

### Spacing Specification

| Element | Current Project |
| --- | --- |
| Safe margin | 64 px |
| Content block gap | 24 px |
| Icon-text gap | 10 px |

## VI. Icon Usage Specification

- **Primary bundled library**: tabler-outline
- **Stroke Width**: 2

| Purpose | Icon Path | Page |
| --- | --- | --- |
| 已完成状态 | tabler-outline/check-circle | P02, P07, P17 |
| 流程与评测 | tabler-outline/route, chart-bar, microscope | P04, P08, P10, P15 |
| 风险提示 | tabler-outline/alert-triangle | P13, P14, P17 |

## VII. Visualization Reference List

| Page | Template | Path | Summary-quote (verbatim) | Usage |
| --- | --- | --- | --- | --- |
| P16 | column_chart | templates/charts/column_chart.svg | Pick for single-series category value comparison, 3-8 categories. Skip for >12 long-label items (use horizontal_bar_chart) or multi-series (use grouped_bar_chart). | 三个 baseline 的得分率与胜平负对比 |
| P17 | stacked_bar_chart | templates/charts/stacked_bar_chart.svg | Pick when each category splits into 2-4 internal parts and total still matters. Skip if only comparing totals (use column_chart). | 八维票型采用压缩示意比例，准确票数为最终口径 |
| P18 | stacked_bar_chart | templates/charts/stacked_bar_chart.svg | Pick when each category splits into 2-4 internal parts and total still matters. Skip if only comparing totals (use column_chart). | 对纯 LLM 的八维平方根压缩票型 |
| P19 | stacked_bar_chart | templates/charts/stacked_bar_chart.svg | Pick when each category splits into 2-4 internal parts and total still matters. Skip if only comparing totals (use column_chart). | 对智谱 GLM 的八维平方根压缩票型 |
| P22 | column_chart | templates/charts/column_chart.svg | Pick for single-series category value comparison, 3-8 categories. Skip for >12 long-label items (use horizontal_bar_chart). | 合并后 10 条 Query 的两组消融得分率并列展示 |

- gauge_chart | rejected for P10: 只能突出单一指标，无法同时表达三组对比与胜平负。
- horizontal_bar_chart | rejected for P11: 页面需要保留完整方法、平票与 baseline 三段构成，堆叠结构更匹配。
- bubble_chart | rejected for P12: 需要明确的象限语义和行动分区。
- gauge_chart | rejected for P14: 两个消融条件必须并列比较而非单 KPI。

## VIII. Image Resource List

| Filename | Dimensions | Ratio | Purpose | Type | Layout pattern | Crop Policy | Acquire Via | Status | Reference | text_policy | page_role |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| images/frontend_interaction_process.png | 1265 × 712 | 1.777 | 真实任务的架构执行总览、S1–S6 和关键事件审计回放 | screenshot | #19 Image floating in whitespace with thin frame and caption + #70 thin colored matte frame | no-crop | user | Existing | 本地前端交互过程页 | preserve | evidence |
| images/frontend_capability_profile.png | 1265 × 712 | 1.777 | 6 个装备能力方向、优先级与置信度画像 | screenshot | #19 Image floating in whitespace with thin frame and caption + #70 thin colored matte frame | no-crop | user | Existing | 本地前端能力画像页 | preserve | evidence |
| images/frontend_research_report.png | 1265 × 712 | 1.777 | 三层九项深度研究报告正文与评审入口 | screenshot | #19 Image floating in whitespace with thin frame and caption + #70 thin colored matte frame | no-crop | user | Existing | 本地前端报告评审页 | preserve | evidence |
| images/frontend_benchmark_overview.png | 1265 × 712 | 1.777 | Benchmark 运行配置与历史记录真实前端证据 | screenshot | #19 Image floating in whitespace with thin frame and caption + #70 thin colored matte frame | no-crop | user | Existing | 本地前端 http://127.0.0.1:5173 | preserve | evidence |
| images/frontend_baseline_merged_result.png | 1265 × 712 | 1.777 | 20 条 Query 的胜平负和八维票型前端证据 | screenshot | #46 bordered lens highlighting a sub-region + #70 thin colored matte frame | no-crop | user | Existing | 本地前端 Benchmark 历史结果 web-benchmark-20260729-082159 | preserve | evidence |
| images/frontend_ablation_overview.png | 1265 × 712 | 1.777 | 三组消融配置与实验记录前端证据 | screenshot | #19 Image floating in whitespace with thin frame and caption + #70 thin colored matte frame | no-crop | user | Existing | 本地前端消融实验页 | preserve | evidence |
| images/frontend_ablation_merged_result.png | 1265 × 712 | 1.777 | 合并后 10 条 Query 的去多源与去制胜机理结果 | screenshot | #46 bordered lens highlighting a sub-region + #70 thin colored matte frame | no-crop | user | Existing | 本地前端 ablation-20260729-merged-q0001-q0010 | preserve | evidence |

## IX. Content Outline

### Part 1: 结论与需求落实

#### Slide 01 - 市场需求发散要求落实与评测汇报

- **Audience move**: 不清楚本阶段完成度 → 建立“已落地、已验证、仍需补强”的整体预期
- **Cover impact**: 以“三层九项已落地 / Benchmark 初步领先 / 下一步补证据与效率”三条短结论构成封面视觉锚点
- **Layout**: 大标题居左，右下为三条结论和日期，使用深蓝竖线与大面积留白
- **Title**: 市场需求发散要求落实与评测汇报
- **Core message**: 本阶段已形成从发散研究、制胜机理到评测闭环的可运行系统。
- **Content**: 副标题“项目落实 · Benchmark · 消融实验”；日期 2026.07；标注“阶段评审”。

#### Slide 02 - 核心结论：主链已跑通，证据与效率是下一阶段重点

- **Audience move**: 等待细节 → 先获得可决策的三点结论
- **Layout**: 三张横向结论卡，底部一条行动建议带
- **Title**: 核心结论
- **Core message**: 方法效果已得到初步支持，但证据事实维度和运行耗时仍制约规模化验证。
- **Content**: ①落实：A–H 发散路径、三层九项、S1–S6、L1–L4、审计恢复已具备；②效果：对通用 Codex Agent 17胜2平1负，得分率90%；③短板：事实证据仍是对通用 Agent 差距最小的维度，平均耗时22.9分钟。
- **Fact IDs**: F-ACC, F-BMK-SUM, F-BMK-DIM, F-BMK-TIME

#### Slide 03 - 原始需求拆解：从发散问题到五项验收

- **Audience move**: 只看到长文档 → 看清需求被拆成四类输入和五项验收
- **Layout**: 左侧四类发散要求，右侧五项验收标准，中间箭头形成映射
- **Title**: 原始需求拆解
- **Core message**: 项目不是泛化检索，而是围绕领域符合性、能力图像、制胜效能、创新性和可实现性收敛。
- **Content**: 四类输入：研究路径发散、场景与战法发散、装备能力与技术发散、验证与交付发散；五项验收：领域属性符合性、装备能力图像、制胜效能、创新性、可实现性。
- **Fact IDs**: F-REQ

#### Slide 04 - 发散问题工程化落实：四层机制控制上下文规模

- **Audience move**: 只知道系统支持发散 → 理解 DOCX 问题如何进入运行时而不膨胀 Prompt
- **Layout**: 上半区四张机制卡，依次为分支内核、Agent 专属镜头、颠覆性种子卡、质量门；下半区为 Query 到五项质量门的十一节点双行流程，完整展示 S1–S6，底部附三条边界规则
- **Title**: 发散问题没有整段复制进 Prompt，而是压缩为四层机制
- **Core message**: 12 类分类提问和 12 张反事实种子通过确定性选择进入唯一责任分支与 S1–S6，既保留发散能力，又避免上下文膨胀。
- **Content**: ①分支内核：12 类问题分配给唯一 A–H 分支或专业 Agent，每个分支只保留一句任务内核；②专属镜头：每个前置 Agent 最多获得三个与职责相关的发散镜头；③种子卡：六类颠覆逻辑压缩为 A1–F2 十二张短卡，通常只选 2–3 张；④质量门：S1 形成竞争性对手体系与反适应假设，S2 形成决策权、力量组织或效应递进不同的作战路径，S3 机制发散，S4 能力映射，S5 差距成熟度，S6 形成 5–7 项具体装备，最终通过五项质量门。边界：本地确定性处理、不增加模型调用；bounded_exploration 最多挑战一个前提；种子不是事实、指标或必选目录。
- **Visualization**: 四层机制卡 + 十一节点双行流程，非数据驱动。
- **Fact IDs**: F-REQ, F-ACC

#### Slide 05 - 分类提问：落实为 A–H 分支和专业 Agent 路由

- **Audience move**: 只知道有 12 类分类问题 → 看清每类问题的唯一主责分支或专业 Agent，理解如何避免重复研究
- **Layout**: 主体为两列 12 行路由表，左列为分类提问，右列为项目主落点；底部补充“唯一主责—前置 Agent 专属镜头—其他 Agent 不重复展开”落实关系
- **Title**: 分类提问落实为 A–H 分支和专业 Agent 路由
- **Core message**: 分类提问的核心价值是确定唯一主责；主分支负责主研究路径，前置专业 Agent 提供少量专属镜头，其他 Agent 不再重复回答同一批问题。
- **Content**: 1局部战争经验与装备启示—C局部战争案例经验；2国际战略形势变化—international_situation Agent；3穿透性制空、反介入/区域拒止—F体系对抗；4人工智能、新材料等颠覆技术—D技术驱动；5全球部署、马赛克、多层防御等对手建设—E对手动向；6马赛克战、决策中心战、分布式杀伤—F体系对抗；7空天、深海等新作战域—G跨域融合；8电磁、网络空间作战—G跨域融合；9“金穹”等多层拦截体系—E对手动向；10智能化、无人化未来战争形态—A新战法；11周边控制、远海前出、远程快打等传统缺口—B传统能力缺口；12新质毁伤与新效应机理—D技术驱动。
- **Visualization**: 数据文本路由表，非数值驱动。
- **Native-ready**: no
- **Fact IDs**: F-REQ

#### Slide 06 - 颠覆型提问：落实为 12 张有界反常规发散种子卡

- **Audience move**: 只知道存在“种子卡” → 看清 12 类原始颠覆提问如何被压缩为有界反事实镜头，并理解智能体仍可自主拓展
- **Layout**: 三列表格完整展示原始颠覆维度、项目种子卡和重点研究关系；底部用边界提示强调种子不是固定答案或装备清单
- **Title**: 颠覆型提问落实为 12 张有界反常规发散种子卡
- **Core message**: 十二张卡提供可控的起始发散空间，但不是封闭目录；智能体可在 Query 因果约束和质量门下提出 OTHER 新方向。
- **Content**: 拦截经济学反转—A1成本强加—单件性能竞争到体系交换比竞争；前线弹药工厂—A2制造即战力—后方库存到分布式按需制造；徘徊火力云—B1持续火力场—临时发射到战区持续存在；和平预置、战时激活—B2预置任务节点—战时部署到预先部署和可信激活；毁平台转向毁节奏—C1决策节奏对抗—物理摧毁到压缩或扰乱决策周期；越打越聪明—C2战役内学习—固定策略到批次间快速学习；非动能点穴瘫痪—D1功能压制—结构毁伤到关键功能失效；打击作为战略信号—D2战略信号—单纯毁伤到打击与认知效应结合；任意传感器匹配最优射手—E1火力即服务—平台绑定到传感器与射手解耦；蜂群对蜂群—E2集群对抗生态—单平台对抗到算法和种群对抗；算法威慑、选择性透明—F1可验证自主—黑箱自主到可约束可验证自主；越降级越自主—F2拒止环境自主—网络依赖到断链条件下任务自治。
- **Visualization**: 数据文本表格，非数值驱动。
- **Native-ready**: no
- **Fact IDs**: F-REQ

#### Slide 07 - 落实矩阵：三层九项与工程闭环均已具备

- **Audience move**: 怀疑需求只停留在文档 → 确认主要要求有运行与验收证据
- **Layout**: 三层九项矩阵为主体，右侧工程能力状态列，绿色勾选为主
- **Title**: 发散要求落实矩阵
- **Core message**: 需求层、技术层、决策层均已映射为明确产物，并通过运行验收。
- **Content**: 第一层①场景②战法/机理③能力特征；第二层④实现途径⑤核心技术⑥耦合短板；第三层⑦装备映射⑧演示验证⑨优先级抓手。工程侧列出 A–H、证据链、审计、恢复、并发、release_ready=true。
- **Visualization**: 非数据驱动状态矩阵。
- **Native-ready**: no
- **Fact IDs**: F-ACC, F-REQ

#### Slide 08 - 项目主链：输入—研究—推理—交付—审计

- **Audience move**: 知道模块存在 → 理解模块如何共同形成可追溯结果
- **Layout**: 五阶段水平流程，S1–S6 与 L1–L4 作为研究和推理阶段的双层泳道
- **Title**: 项目主链已形成闭环
- **Core message**: 从 Query 到能力画像的每一步均留下结构化产物和审计状态。
- **Content**: Query/模板 → A–H 路由与多源研究 → S1–S6 制胜机理 → 三层九项报告/能力画像 → L1–L4 复核、审计与恢复。
- **Visualization**: 非数据驱动流程图。
- **Fact IDs**: F-ACC, F-HARNESS

#### Slide 09 - 三层九项合同：发散不等于失控

- **Audience move**: 担心发散输出不可控 → 看到固定产物合同和收敛机制
- **Layout**: 三层阶梯或金字塔，每层三项；右侧强调“每项有输入、产物、验证”
- **Title**: 三层九项把发散研究约束为可验收产物
- **Core message**: 允许研究路径发散，但交付结构、证据要求和验证口径保持稳定。
- **Content**: 逐层列出九项，并在底部标注 S1–S6 负责机理收敛、L1–L4 负责质量回路。
- **Visualization**: 非数据驱动金字塔结构。
- **Fact IDs**: F-REQ, F-HARNESS

### Part 2: 前端交付效果

#### Slide 10 - 前端效果总览：从过程、画像到报告均可直接验收

- **Audience move**: 只看到架构与合同 → 看到可操作、可追溯、可交付的真实产品形态
- **Layout**: 三张截图组成不等宽横向画廊，底部用“过程—画像—报告”三段箭头串联
- **Title**: 核心发散能力已形成可验收前端闭环
- **Core message**: 发散研究不再停留在后台流程，交互审计、能力画像和研究报告均已成为可见、可查、可复用的产品能力。
- **Content**: 交互过程支持 426 个事件与 9 个保存点回放；能力画像输出 6 个装备方向；报告评审呈现三层九项正文。
- **Images**: images/frontend_interaction_process.png; images/frontend_capability_profile.png; images/frontend_research_report.png
- **Visualization**: 三联截图画廊，非数据驱动。
- **Fact IDs**: F-ACC

#### Slide 11 - 交互过程：研究链路、专用 Agent 与审计事件全程可回放

- **Audience move**: 相信系统能运行 → 确认每一步可观察、可定位、可恢复
- **Layout**: 左侧大幅前端截图，右侧为 426 事件、80 关键事件、6/6 S Agent、9 保存点四项指标
- **Title**: 交互过程把复杂研究链变成可审计执行记录
- **Core message**: 单次任务同时展示架构执行总览、S1–S6 结果、L1–L4 循环和关键事件，支持问题定位与复盘。
- **Content**: 代表任务“强干扰、弱通信条件下低信息依赖精确打击研究”；全部事件426，关键事件80，S1–S6 6/6完成，保存点9。
- **Images**: images/frontend_interaction_process.png
- **Visualization**: 截图证据与 KPI 指标卡。
- **Fact IDs**: F-ACC

#### Slide 12 - 能力画像：从研究判断收敛到 6 个具体装备方向

- **Audience move**: 看到研究过程 → 确认输出能够落实到装备方向、优先级和验证路径
- **Layout**: 右侧大幅截图，左侧突出“6 个方向 / 1 个高优先级 / 79% 平均置信度”，下方列出现役升级与新能力谱系
- **Title**: 能力画像已能给出装备方向、谱系位置与实现路径
- **Core message**: 系统把场景和制胜机理映射为现役升级与新能力方向，并保留优先级、置信度、差距和演化路径。
- **Content**: 6 个方向，1 个高优先级，平均置信度79%；示例包括现役纵深导弹火力升级、低信息远程精确导弹族、低信息侦打巡飞弹等。
- **Images**: images/frontend_capability_profile.png
- **Visualization**: 截图证据与能力谱系摘要。
- **Fact IDs**: F-ACC

#### Slide 13 - 研究报告：三层九项已形成可阅读、可评审的正式产物

- **Audience move**: 确认方向存在 → 确认成果能以正式报告交付并支撑评审
- **Layout**: 左侧大幅报告截图，右侧用三层九项结构摘要与“事实—推断—待验证”边界提示
- **Title**: 三层九项已沉淀为可直接评审的深度研究报告
- **Core message**: 报告将典型场景、制胜机理、装备画像、核心技术、风险和效能贡献组织为一致交付结构。
- **Content**: 第一层需求挖掘，第二层技术攻关，第三层能力图像与效能贡献；正文保留证据边界与待验证项。
- **Images**: images/frontend_research_report.png
- **Visualization**: 截图证据与三层九项结构摘要。
- **Fact IDs**: F-REQ, F-ACC

### Part 3: Benchmark 设计与结果

#### Slide 14 - Benchmark 思路：真实产物复用 + 匿名双顺序盲评

- **Audience move**: 只看到胜率 → 理解比较对象、样本与防偏置设计
- **Layout**: 左侧测试流程图，右侧嵌入前端总览截图并配口径说明
- **Title**: Benchmark 测试思路
- **Core message**: 用同一 Query 比较四套系统，复用真实研究报告，并通过 A/B 与 B/A 双顺序降低位置偏置。
- **Content**: 20 条 Query；4 系统；80 份回答；120 Pair；2 名 GPT-5.5 judge；judge error=0；完整方法对通用 Agent、纯 LLM、智谱 GLM。
- **Images**: images/frontend_benchmark_overview.png
- **Visualization**: 数据驱动流程与 KPI 卡。
- **Fact IDs**: F-BMK-DESIGN

#### Slide 15 - 评测标准：五项验收落到八个可判维度

- **Audience move**: 担心评测主观 → 看清业务要求如何转化为一致评审口径
- **Layout**: 左侧五项业务验收，右侧八维评测，使用连线强调多对多映射
- **Title**: 从五项要求到八维评测标准
- **Core message**: 胜负不是按篇幅或术语，而是按任务完成、事实证据、机理、能力映射、价值、前瞻、稳健和不确定性判断。
- **Content**: 八维：路径与任务完成、证据与事实可靠性、因果与机理深度、军事运用价值、能力映射与需求质量、前瞻创新性、体系与跨场景稳健性、不确定性与验证。
- **Visualization**: 非数据驱动标准映射图。
- **Fact IDs**: F-JUDGE

#### Slide 16 - Benchmark 总结果：对三类基线均领先

- **Audience move**: 了解测试方法 → 获得总体效果结论与不确定性边界
- **Layout**: 左侧三组胜平负柱形/卡片，右侧前端结果截图；底部标注 Bootstrap 区间
- **Title**: Benchmark 总结果
- **Core message**: 完整方法对最强通用 Codex Agent 得分率90%，对两类纯模型均为97.5%。
- **Content**: vs 通用 Codex Agent：17胜2平1负，90%，95%区间78%–100%；vs 纯 LLM：19胜1平0负，97.5%；vs 智谱：19胜1平0负，97.5%。
- **Images**: images/frontend_baseline_merged_result.png
- **Visualization**: 数据驱动列图与置信区间注释，参考 column_chart。
- **Native-ready**: no
- **Fact IDs**: F-BMK-SUM

#### Slide 17 - 对通用 Codex Agent：八维全部领先，证据维度差距最小

- **Audience move**: 只看到总体胜率 → 识别八维优势分布与仍需加强的证据维度
- **Layout**: 八条横向堆叠票型为主体，右侧展示总体得分率、胜平负与最小领先维度
- **Title**: 对通用 Codex Agent 的八维票型
- **Core message**: 完整方法以 17 胜 2 平 1 负、得分率 90% 领先，八个维度均保持正向；证据与事实可靠性的领先幅度最小。
- **Content**: 总体为完整方法17胜2平1负、得分率90%、95%区间78%–100%；通用 Codex Agent 1胜2平17负、得分率10%、95%区间0%–23%。分维度票型为：能力映射73:0:7；因果机理68:0:12；事实证据38:16:26；军事价值72:1:7；前瞻新颖76:2:2；任务完成71:1:8；体系稳健68:3:9；不确定性66:7:7。
- **Visualization**: 数据驱动横向三段堆叠条，延续平方根压缩示意并适度收短通用 Codex Agent 橙色段；右侧保留总体胜平负和准确分维票数，参考 stacked_bar_chart。
- **Native-ready**: no
- **Fact IDs**: F-BMK-DIM

#### Slide 18 - 对纯 LLM：八个维度均形成压倒性优势

- **Audience move**: 看到总体 19胜1平 → 看清优势覆盖所有评测维度
- **Layout**: 八条横向堆叠票型为主体，右侧突出“事实证据、前瞻创新、不确定性验证均 80:0:0”
- **Title**: 对纯 LLM 的八维票型
- **Core message**: 完整方法在全部八个维度领先，事实证据、前瞻创新和不确定性验证三个维度由双 Judge 全票支持。
- **Content**: 任务完成74:0:6；事实证据80:0:0；因果机理76:0:4；能力映射75:0:5；不确定性80:0:0；军事价值78:0:2；前瞻创新80:0:0；体系稳健71:2:7。
- **Visualization**: 数据驱动横向三段堆叠条，采用平方根压缩比例增强 Baseline 少数票段可读性；右侧保留准确票数，参考 stacked_bar_chart。
- **Native-ready**: no
- **Fact IDs**: F-BMK-DIM

#### Slide 19 - 对智谱 GLM：八维优势同样稳定

- **Audience move**: 只知道总体领先 → 确认对另一类模型基线仍保持跨维度稳定性
- **Layout**: 八条横向堆叠票型为主体，右侧突出“事实证据、体系稳健均 80:0:0”
- **Title**: 对智谱 GLM 的八维票型
- **Core message**: 完整方法在八个维度全部领先，其中事实证据和体系稳健获得双 Judge 全票支持。
- **Content**: 任务完成78:0:2；事实证据80:0:0；因果机理78:0:2；能力映射78:0:2；不确定性80:0:0；军事价值78:0:2；前瞻创新76:1:3；体系稳健80:0:0。
- **Visualization**: 数据驱动横向三段堆叠条，采用平方根压缩比例增强 Baseline 少数票段可读性；右侧保留准确票数，参考 stacked_bar_chart。
- **Native-ready**: no
- **Fact IDs**: F-BMK-DIM

#### Slide 20 - Benchmark 结论：深度调研需要专业 Agent 系统

- **Audience move**: 看完三组结果但仍把优势归因于基模能力 → 理解基模、通用 Agent 与专业 Agent 系统在深度调研中的不同职责
- **Layout**: 上部三列分别对比纯 LLM、智谱 GLM 和通用 Codex Agent 的优势、局限与结果；下部以专业 Agent 系统的研究链和一句总判断收束
- **Title**: Benchmark 说明：深度调研任务需要专业 Agent 系统
- **Core message**: 基模提供认知与生成能力，通用 Agent 提供工具执行框架，专业 Agent 系统负责组织多角色研究、机制推演、证据审计和稳定交付。
- **Content**: 纯 LLM 与智谱 GLM 生成快、成本低、表达能力强，但缺少多源研究、过程状态、证据审计、机制推演和交付合同，完整方法对两者均为19胜1平0负、得分率97.5%；通用 Codex Agent 具备工具调用和一般任务执行能力，但缺少领域路由、S1–S6、三层九项、能力画像与L1–L4质量循环，完整方法为17胜2平1负、得分率90%，证据维度差距最小；专业 Agent 系统把搜索与生成升级为“多角色研究—机理推演—能力映射—装备收敛—证据审计”，适合复杂、长链条、多来源、强领域约束且要求可追溯正式交付的任务。
- **Visualization**: 三类基线能力阶梯 + 专业 Agent 系统闭环，非数据驱动。
- **Native-ready**: no
- **Fact IDs**: F-BMK-SUM, F-BMK-DIM, F-ACC, F-HARNESS

### Part 4: 消融与下一步

#### Slide 21 - 消融设计：分别验证多源基线与制胜机理贡献

- **Audience move**: 知道整体有效 → 理解哪些模块可能贡献效果
- **Layout**: 三列实验臂对照，底部展示合并后 10 条 Query、双 Judge 与探索性限制；嵌入前端配置截图
- **Title**: 消融实验设计
- **Core message**: 固定其余流程，分别移除多源基线和 S1–S6 制胜机理，观察质量与耗时变化。
- **Content**: 完整方法：多角色多通道+S1–S6+L1–L4；去多源：单受限通用检索 Agent+S1–S6+L1–L4；去制胜机理：多源基线，跳过S1–S6，循环关闭。合并样本10条，结果仍为探索性。
- **Images**: images/frontend_ablation_overview.png
- **Visualization**: 非数据驱动实验臂对照图。
- **Fact IDs**: F-ABL-DESIGN

#### Slide 22 - 消融结果：制胜机理贡献明确，多源贡献需扩大样本复测

- **Audience move**: 等待模块结论 → 区分“得到支持”和“仅方向性证据”
- **Layout**: 左侧两组消融得分率与耗时列图，右侧前端结果截图与结论标签
- **Title**: 合并后消融实验结果
- **Core message**: 制胜机理是当前最强增益来源，多源研究呈方向性增益；两项结论均需在同版本、扩样本条件下复测。
- **Content**: 完整方法 vs 去多源基线：60% vs 40%，Δ20%，说明多源研究提供方向性增益；完整方法 vs 去制胜机理：95% vs 5%，Δ90%，说明 S1–S6 制胜机理是核心贡献信号。两组均由匿名 A/B、正反序和双 Judge 评审；由于控制组版本和样本仍有限，应固定代码、模型、Query 与 Judge 后扩样复测，再形成稳定因果证据。
- **Images**: images/frontend_ablation_merged_result.png
- **Visualization**: 数据驱动成对列图与分维度票型摘要，参考 column_chart。
- **Native-ready**: no
- **Fact IDs**: F-ABL-RESULT

#### Slide 23 - 下一阶段：补优化、扩样本、降时延

- **Audience move**: 接受阶段结果 → 同意三项可执行工作包和验收口径
- **Closing impact**: 用“三项工作包 + 明确验收”收束，形成可直接决策的结束页
- **Layout**: 三个编号工作包，右下角为阶段目标和建议决策
- **Title**: 下一阶段建议
- **Core message**: 下一阶段不再扩大方法复杂度，优先优化智能体设计、扩大统计样本并完成同版本复测。
- **Content**: ①优化智能体设计：严格落实相关要求；②50条全量 Benchmark：固定代码与模型版本、预注册评测口径、报告置信区间；③同版本消融复测：完整方法同批运行，记录质量/时延/成本，形成稳定因果证据。建议决策：批准三项工作包进入下一阶段。
- **Fact IDs**: F-BMK-DIM, F-BMK-TIME, F-ABL-RESULT

## X. Speaker Notes Requirements

- **Filename**: match each SVG filename under `notes/`
- **Content**: 每页给出60–90秒讲解要点、数据口径、限定条件和过渡语；事实仅引用 sources 中的需求文档、验收 JSON、Benchmark 与消融产物，不补造数据。
- **Total duration**: 15–20 minutes
- **Notes style**: formal, concise, evidence-led
- **Presentation purpose**: report and persuade
