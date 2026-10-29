# 智能对话与深研对话三类检索质量验收

验收日期：2026-10-20（Asia/Shanghai）

项目 Query：`query-30510033-b96d-46e8-8a3a-48ffe2b07e8e` — 低空无人集群复杂电磁环境闭环反制装备研究

真实模型：`siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash`

## 结论

智能对话与深研对话均完成 Open Websearch、AMiner 和知识库真实检索，并通过相关性、来源质量、完整摘要、知识库相似度、最终证据边界及工具协议泄漏检查。

| 入口 | Run ID | 用时 | Open Websearch | AMiner | 知识库 |
| --- | --- | ---: | --- | --- | --- |
| 智能对话 | `b4f3dcdb-bd1c-4957-8410-0a1680f4deac` | 303.2 秒 | 5 次；14 条结果；13 个 URL；4 条权威来源；主题相关率 100% | 9 次搜索；20 个候选；2 篇完整摘要；0 次供应商失败 | 2 次；20 个片段；7 份文献；最高相似度 0.747 |
| 深研对话 | `9a3750d5-a24b-4578-b7ac-4c5d47982e41` | 85.6 秒 | 4 次；6 条结果；6 个 URL；1 条权威来源；主题相关率 100% | 2 次搜索；1 个候选；1 篇完整摘要；0 次供应商失败 | 1 次；10 个片段；5 份文献；最高相似度 0.725 |

## 证据质量

- Open Websearch 的高质量命中包括 MDPI 与 ScienceDirect 论文出版页。两条回答均明确指出本轮没有取得政府/军队一手页面，未把厂商和聚合页提升为同等证据。
- 智能对话取得 `Review and Simulation of Counter-UAS Sensors for Unmanned Traffic Management` 和 `A Review of Counter-UAS Technologies for Cooperative Defensive Teams of Drones` 的完整摘要。
- 深研对话取得 `Evaluation of Safety Zones Created by Hybrid UAV Detection and Jamming System` 的完整摘要。
- 知识库核心命中包括《群对群拦截协同态势感知关键技术》《探测-干扰-通信一体化管控策略研究》《雷达主瓣反干扰研究进展及展望》和《一种面向电磁对抗的体系效能机理反演分析模型》。
- 两条最终正文都区分了网页公开事实、AMiner 摘要、知识库内部文献和待验证工程推断，并给出可点击网页、论文 DOI 与知识库文件名。

## 运行边界

平台要求消息正文包含显式 `@知识库` 标记；只传知识库 ID 会被 opt-in 中间件关闭知识库工具。一次早期预跑因此被判为无效并中止。另一次强研究预跑在模型供应商多次断流后触发 Worker lease 过期，不纳入本结论。最终验收使用相同 Query，收窄为检索与证据融合任务并禁用非必要子智能体，两条 Run 均正常完成。

完整工具审计、最终正文和质量检查见 [validation.json](./validation.json)。
