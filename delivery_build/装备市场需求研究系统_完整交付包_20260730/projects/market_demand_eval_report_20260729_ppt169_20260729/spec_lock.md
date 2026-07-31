<!-- ppt-master-schema: spec-lock/v1 -->
# Execution Lock

## canvas
- viewBox: 0 0 1280 720
- format: PPT 16:9

## communication
- audience: 项目管理层、业务需求方与技术评审人员
- objective: 汇报发散需求落实与评测证据，推动证据质量专项、50条全量Benchmark和同版本消融复测获得批准。
- core_message: 三层九项、制胜机理与评测闭环已落地且初步有效，下一阶段优先补强证据绑定、扩大样本并降低时延。

## mode
- mode: pyramid

## visual_style
- visual_style: swiss-minimal

## colors
- background: #FFFFFF
- secondary_background: #F3F6F9
- primary: #173B5E
- accent: #2F6FAE
- secondary_accent: #2E8B66
- body_text: #1D2733
- risk: #C97A32
- muted: #6B7785

## typography
- font_family: PingFang SC, Arial, Microsoft YaHei, sans-serif
- title_family: PingFang SC, Arial, Microsoft YaHei, sans-serif
- body_family: PingFang SC, Arial, Microsoft YaHei, sans-serif
- data_family: Arial, PingFang SC, Microsoft YaHei, sans-serif
- body: 24
- title: 42
- subtitle: 32
- annotation: 18
- data: 30
- hero: 66

## icons
- library: tabler-outline
- inventory: check-circle, route, chart-bar, microscope, alert-triangle
- stroke_width: 2

## images
- P10: images/frontend_interaction_process.png; images/frontend_capability_profile.png; images/frontend_research_report.png | source=user | pattern=#49 asymmetric collage + #70 thin colored matte frame | crop=no-crop
- P11: images/frontend_interaction_process.png | source=user | pattern=#19 Image floating in whitespace with thin frame and caption + #70 thin colored matte frame | crop=no-crop
- P12: images/frontend_capability_profile.png | source=user | pattern=#19 Image floating in whitespace with thin frame and caption + #70 thin colored matte frame | crop=no-crop
- P13: images/frontend_research_report.png | source=user | pattern=#19 Image floating in whitespace with thin frame and caption + #70 thin colored matte frame | crop=no-crop
- P14: images/frontend_benchmark_overview.png | source=user | pattern=#19 Image floating in whitespace with thin frame and caption + #70 thin colored matte frame | crop=no-crop
- P16: images/frontend_baseline_merged_result.png | source=user | pattern=#46 bordered lens highlighting a sub-region + #70 thin colored matte frame | crop=no-crop
- P21: images/frontend_ablation_overview.png | source=user | pattern=#19 Image floating in whitespace with thin frame and caption + #70 thin colored matte frame | crop=no-crop
- P22: images/frontend_ablation_merged_result.png | source=user | pattern=#46 bordered lens highlighting a sub-region + #70 thin colored matte frame | crop=no-crop

## page_charts
- P16: column_chart
- P17: stacked_bar_chart
- P18: stacked_bar_chart
- P19: stacked_bar_chart
- P22: column_chart

## page_rhythm
- P01: anchor
- P02: anchor
- P03: dense
- P04: dense
- P05: dense
- P06: dense
- P07: dense
- P08: breathing
- P09: anchor
- P10: breathing
- P11: dense
- P12: dense
- P13: dense
- P14: dense
- P15: dense
- P16: anchor
- P17: dense
- P18: dense
- P19: dense
- P20: anchor
- P21: dense
- P22: anchor
- P23: anchor

## pptx_structure
- mode: flat

## forbidden
- `mask`, `<style>`, `class`, external CSS, `<foreignObject>`, `textPath`, `@font-face`, `<animate*>`, `<set>`, `<script>` / event attributes, `<iframe>`
- HTML named entities in text; write typography as raw Unicode and escape XML reserved characters
