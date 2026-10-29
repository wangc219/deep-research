# 调研检索增强云端部署验收

部署日期：2026-10-19（Asia/Shanghai）

云端：`ubuntu@49.232.128.56`，项目目录 `/opt/deep-research`，公网入口 `https://www.deepquest.space`

## 结论

本轮 Open Websearch、AMiner、调研探索员与智能/深研对话编排已同步到云端并投入运行。最终 API 镜像为
`sha256:3e02486433ef8c8aaf061b61b2ae2767f1cac120598eb44be2c03697b5036211`；内网和公网 readiness 均为
`ready`，PostgreSQL、Redis、Worker、默认 Agent、知识库、模型供应商等必需组件均为 `ok`。

云端生产设置已按要求调整：Open Websearch 使用当前地域可用性更好的 `baidu,bing`，AMiner 的 8 个应用侧费用/次数配置全部为 0
（不限额）。AMiner 空主题结果增加了自动标题补救：主题词压缩后走免费标题检索，再对候选读取完整摘要。

## 部署与回滚点

- 主部署：`research-search-quality-20261019T212827`
  - 备份：`/var/backups/deepquest/research-search-quality-20261019T212827`
- 云端搜索地域适配：`research-search-cloud-fix-20261019T215113`
  - 备份：`/var/backups/deepquest/research-search-cloud-fix-20261019T215113`
- AMiner 标题补救：`aminer-title-fallback-20261019T221716`
  - 备份：`/var/backups/deepquest/aminer-title-fallback-20261019T221716`

各部署均在执行前确认无活跃任务，备份被覆盖源码并保存旧 API 镜像；源码逐文件 SHA-256 校验一致。

## 确定性验证

- 主回归：158 passed，10 skipped。
- Open Websearch 增量：45 passed。
- AMiner 增量：48 passed。
- PostgreSQL 中 `default-chatbot`、`deep-research`、`research-explorer` 的持久化提示已包含精确主题锚点、权威来源、
  AMiner 标题桥接和高价值交付规则。
- 云端真实 Open Websearch smoke：返回 3 条有效结果。
- 云端真实 AMiner smoke：`topic` 空命中后，`title_fallback` 命中 1 篇，并取得 1140 字符完整摘要。
- 最近 API/Worker 日志未发现 `ERROR`、`Traceback` 或 `CRITICAL`。

## 真实模型验收

项目 Query：`query-30510033-b96d-46e8-8a3a-48ffe2b07e8e` — 低空无人集群复杂电磁环境闭环反制装备研究。

本地最终双入口基准已全部通过：智能对话 218.9 秒，深研 229.6 秒，总计 448.5 秒。

云端最终代码的智能对话 Run：`1e8531a0-b389-436b-a6e1-b69610e6bcb1`。功能与证据链已跑通：

- 2 个正交探索员；
- 7 次有效 Web 检索，全部带 `required_terms`；
- 10 个去重网页来源、2 个权威来源；
- 20 次 AMiner 调用，0 失败；
- 主题检索与标题检索均命中；
- 取得 3 篇完整摘要；
- 最终输出为完整正文，包含具体装备与最小验证动作，未泄漏工具协议。

该云端 Run 用时 731.7 秒，超过 600 秒效率门槛；主要瓶颈是模型供应商延迟（单次模型调用最高 331.5 秒），不是 Websearch
或 AMiner 额度/失败。严格验收器另有两项未通过：其中“完整摘要相关性”未把直接相关标题中的 `UAS` 识别为 `UAV`，属于校验词表误判；
“证据塑造生成”是最终正文未出现验收器约定短语。故云端记录为“检索链与生成链功能通过，端到端时延待持续观察”，不虚报为全门槛通过。

结构化数据见 [validation.json](./validation.json)。
