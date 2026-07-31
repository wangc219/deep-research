<!-- ppt-master-schema: spec-lock/v1 -->
# Execution Lock

## canvas
- viewBox: 0 0 1280 720
- format: PPT 16:9

## communication
- audience: 甲方项目负责人、业务领域专家、技术负责人及验收管理人员
- objective: 用真实系统、验收与盲评证据证明三类闭环已初步落地，使甲方认可专业质量优势，并就智能体编排、业务流程和 Benchmark 三项下一阶段重点达成共识。
- core_message: 核心闭环已初步落地且真实专家盲评验证机理推演、能力映射和体系分析优势；下一阶段重点优化智能体设计与协作编排、完善端到端业务执行流程，并通过 Pairwise 盲评和模块消融实验持续完善 Benchmark。
- consumption_mode: balanced

## mode
- mode: pyramid

## visual_style
- visual_style: soft-rounded

## colors
- background: #F7F9FC
- secondary_bg: #EAF0F7
- primary: #123B63
- accent: #D59A24
- secondary_accent: #2A7F9E
- body_text: #17212B
- muted_text: #5B6B7C
- positive: #2E8B6D
- warning: #C87919
- negative: #B94747
- surface: #FFFFFF
- grid: #D7E0EA
- image_rendering: flat

## typography
- font_family: Arial, "Microsoft YaHei", "PingFang SC", SimHei, sans-serif
- title_family: Georgia, "Noto Serif CJK SC", "Songti SC", SimSun, serif
- body_family: Arial, "Microsoft YaHei", "PingFang SC", SimHei, sans-serif
- data_family: Arial, "Microsoft YaHei", "PingFang SC", sans-serif
- footnote_family: Arial, "Microsoft YaHei", "PingFang SC", sans-serif
- body: 24
- title: 42
- section_title: 36
- subtitle: 32
- lead: 30
- compact_label: 21
- metric_medium: 38
- annotation: 18
- footnote: 14

## icons
- library: tabler-outline
- stroke_width: 2
- inventory: tabler-outline/target-arrow, tabler-outline/route-2, tabler-outline/robot, tabler-outline/users-group, tabler-outline/shield-check, tabler-outline/database, tabler-outline/activity, tabler-outline/git-branch, tabler-outline/search, tabler-outline/file-check, tabler-outline/chart-bar, tabler-outline/clock, tabler-outline/alert-triangle, tabler-outline/rocket, tabler-outline/checklist, tabler-outline/layers-linked, tabler-outline/network, tabler-outline/timeline

## images
- p01_p17: images/cover_multi_agent_closed_loop.png | source=ai | pattern=#1 Full-bleed background with floating title + #30 Flat semi-transparent rectangle overlay + #65 Image with NO text — labels added as native SVG | crop=adaptive
- p10: images/workbench_home.png | source=user | pattern=#19 Image floating in whitespace with thin frame and caption + #36 Drop shadow under image panel | crop=no-crop
- p11: images/interaction_gate_overview_v2.jpg | source=user | pattern=#19 Image floating in whitespace with thin frame and caption + #70 Image with thin colored matte frame | crop=no-crop
- p11_recall_request: images/interaction_recall_request_v2.jpg | source=user | pattern=#48 Side-by-side comparison + #70 Image with thin colored matte frame | crop=no-crop
- p11_recall_complete: images/interaction_recall_complete_v2.jpg | source=user | pattern=#48 Side-by-side comparison + #70 Image with thin colored matte frame | crop=no-crop
- p12: images/architecture_execution_overview.png | source=user | pattern=#38 Background image + annotation cards with bezier leader lines + #70 Image with thin colored matte frame | crop=no-crop
- p13: images/capability_view.png | source=user | pattern=#80 Side hero image + staggered evidence cards + #70 Image with thin colored matte frame | crop=no-crop
- p16: images/benchmark_results.png | source=user | pattern=#18 Image as full-height sidebar column + #70 Image with thin colored matte frame | crop=no-crop

## page_charts
- P16: stacked_bar_chart

## page_rhythm
- P01: anchor
- P02: dense
- P03: anchor
- P04: dense
- P05: anchor
- P06: dense
- P07: anchor
- P08: anchor
- P09: dense
- P10: breathing
- P11: dense
- P12: breathing
- P13: dense
- P14: dense
- P15: dense
- P16: dense
- P17: anchor

## pptx_structure
- mode: flat

## forbidden
- `mask`, `<style>`, `class`, external CSS, `<foreignObject>`, `textPath`, `@font-face`, `<animate*>`, `<set>`, `<script>` / event attributes, `<iframe>`
- HTML named entities in text; write typography as raw Unicode and escape XML reserved characters
