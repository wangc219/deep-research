<!-- ppt-master-schema: spec-lock/v1 -->
# Execution Lock

## canvas
- viewBox: 0 0 1280 720
- format: PPT 16:9

## communication
- audience: 项目方管理层、业务与技术负责人
- objective: 用项目方易懂的故事讲清“需求 Query”是双入口、异步运行、可审核发布的选题发现服务，并说明共享 S1–S6 主链下质量集群如何快速把方向摸稳、动态蜂群如何按缺口补齐并守住正式结论质量；以真实前端页面证明从选题、推演、证据到报告交付的闭环已可演示。
- core_message: 面对同一研究难题，Query 服务先把选题从一次性标题生成变成可联网校验与审核的研究入口；质量集群像固定专家组快速会诊，动态蜂群像按问题临时增援的专项团队；共同把不可靠问题和候选挡在正式交付之前。
- consumption_mode: balanced

## mode
- mode: custom
- mode_behavior: 按“需求 Query”双入口与共用异步质量链、共同研究主线、两种带队方式、质量提升证据、前端闭环交付与下一步推进；前端章节以真实截图串起选题生成、任务推演、证据核验、报告评审，强调同一任务可在各视图之间下钻；Query 章节突出母题模式由用户定义边界、自动态势模式由系统定义领域边界并由 Agent 选择切入点，二者均进入联网校验、结构化生成、质量门和人工审核发布；蜂群章节用“固定专家组”与“按问题临时增援”的大白话类比解释机制，技术术语只作为事实落点；明确 Kimi K3 仅为方法启发，项目实现是自身的 winning_swarm_dynamic_v2。

## visual_style
- visual_style: swiss-minimal

## colors
- background: #F8FAFC
- secondary_background: #EAF0F7
- primary: #0D2B55
- accent: #E89A22
- secondary_accent: #2B78B8
- body_text: #18212F

## typography
- font_family: Microsoft YaHei, Arial, sans-serif
- title_family: Microsoft YaHei, Arial, sans-serif
- body_family: Microsoft YaHei, Arial, sans-serif
- annotation_family: Microsoft YaHei, Arial, sans-serif
- lead_family: Microsoft YaHei, Arial, sans-serif
- body: 24
- title: 42
- subtitle: 32
- lead: 28
- annotation: 18
- footnote: 16

## icons
- library: tabler-outline
- inventory: search, git-fork, layout-dashboard, arrow-right
- stroke_width: 2

## images
- p03_query_generation: images/frontend_query_generation_live.jpg | source=user | pattern=#19 Image floating in whitespace with thin frame and caption; #70 Image with thin colored matte frame | crop=no-crop
- p10_interaction: images/interaction_view_clean.png | source=user | pattern=#50 Tiled grid (2×2, 2×3, 3×3) with equal cells; #70 Image with thin colored matte frame | crop=no-crop
- p10_capability: images/capability_view_clean.png | source=user | pattern=#50 Tiled grid (2×2, 2×3, 3×3) with equal cells; #70 Image with thin colored matte frame | crop=no-crop
- p10_winning: images/winning_view_clean.png | source=user | pattern=#50 Tiled grid (2×2, 2×3, 3×3) with equal cells; #70 Image with thin colored matte frame | crop=no-crop
- p12_s1_s6: images/frontend_s1_s6_live.jpg | source=user | pattern=#50 Tiled grid (2×2, 2×3, 3×3) with equal cells; #70 Image with thin colored matte frame | crop=no-crop
- p12_evidence: images/frontend_evidence_center_live.jpg | source=user | pattern=#50 Tiled grid (2×2, 2×3, 3×3) with equal cells; #70 Image with thin colored matte frame | crop=no-crop
- p13_report_review: images/frontend_report_review_live.jpg | source=user | pattern=#19 Image floating in whitespace with thin frame and caption; #70 Image with thin colored matte frame | crop=no-crop

## page_rhythm
- P01: anchor
- P02: dense
- P03: breathing
- P04: dense
- P05: dense
- P06: dense
- P07: dense
- P08: dense
- P09: dense
- P10: breathing
- P11: breathing
- P12: breathing
- P13: breathing
- P14: dense
- P15: anchor

## pptx_structure
- mode: flat

## forbidden
- `mask`, `<style>`, `class`, external CSS, `<foreignObject>`, `textPath`, `@font-face`, `<animate*>`, `<set>`, `<script>` / event attributes, `<iframe>`
- HTML named entities in text; write typography as raw Unicode and escape XML reserved characters
