import fs from "node:fs/promises";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const OUT = "/Users/wangchen/equipment research/市场需求落实与评测汇报_20260729.pptx";
const PREVIEW_DIR = "/Users/wangchen/equipment research/.tmp/market-demand-ppt/rendered";

const C = {
  navy: "#16324F",
  blue: "#2563A6",
  cyan: "#2F80A3",
  green: "#2E7D5B",
  amber: "#C88A2B",
  red: "#B5524B",
  ink: "#17202A",
  text: "#334155",
  muted: "#64748B",
  line: "#D7DEE7",
  light: "#F4F7FA",
  paleBlue: "#EAF2F8",
  paleGreen: "#EAF5EF",
  paleAmber: "#FBF3E3",
  white: "#FFFFFF",
};

const FONT = "PingFang SC";
const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });

async function writeBlob(path, blob) {
  await fs.writeFile(path, new Uint8Array(await blob.arrayBuffer()));
}

function addText(slide, text, x, y, w, h, opts = {}) {
  const s = slide.shapes.add({
    geometry: "textbox",
    position: { left: x, top: y, width: w, height: h },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  s.text = text;
  s.text.style = {
    fontFamily: FONT,
    fontSize: opts.fontSize ?? 18,
    bold: opts.bold ?? false,
    color: opts.color ?? C.text,
    alignment: opts.align ?? "left",
    verticalAlignment: opts.valign ?? "middle",
    italic: opts.italic ?? false,
  };
  return s;
}

function addBox(slide, x, y, w, h, opts = {}) {
  const config = {
    geometry: opts.geometry ?? "roundRect",
    position: { left: x, top: y, width: w, height: h },
    fill: opts.fill ?? C.white,
    line: { style: "solid", fill: opts.line ?? C.line, width: opts.lineWidth ?? 1 },
    shadow: opts.shadow,
  };
  if ((opts.geometry ?? "roundRect") === "roundRect") config.borderRadius = opts.radius ?? "rounded-lg";
  return slide.shapes.add(config);
}

function addRule(slide, x, y, w, color = C.line, h = 1) {
  slide.shapes.add({
    geometry: "rect",
    position: { left: x, top: y, width: w, height: h },
    fill: color,
    line: { style: "solid", fill: color, width: 0 },
  });
}

function addHeader(slide, title, kicker, page) {
  slide.background.fill = C.white;
  addText(slide, kicker, 72, 34, 520, 24, { fontSize: 13, bold: true, color: C.blue });
  addText(slide, title, 72, 64, 1136, 52, { fontSize: 36, bold: true, color: C.ink });
  addRule(slide, 72, 124, 1136, C.line, 1);
  addText(slide, String(page).padStart(2, "0"), 1150, 672, 58, 20, { fontSize: 12, color: C.muted, align: "right" });
  addText(slide, "装备能力图像 Deep Research", 72, 672, 360, 20, { fontSize: 12, color: C.muted });
}

function addNotes(slide, sources, extra = "") {
  const body = extra ? `${extra}\n\n` : "";
  slide.speakerNotes.textFrame.setText(`${body}[Sources]\n${sources.map((s) => `- ${s}`).join("\n")}`);
  slide.speakerNotes.setVisible(true);
}

function statusTag(slide, x, y, text, kind = "done") {
  const cfg = kind === "done"
    ? { fill: C.paleGreen, color: C.green }
    : kind === "partial"
      ? { fill: C.paleAmber, color: C.amber }
      : { fill: C.light, color: C.muted };
  addBox(slide, x, y, 88, 30, { fill: cfg.fill, line: cfg.fill, radius: "rounded-md" });
  addText(slide, text, x, y, 88, 30, { fontSize: 14, bold: true, color: cfg.color, align: "center" });
}

function bulletList(slide, items, x, y, w, lineH = 44, opts = {}) {
  items.forEach((item, i) => {
    const yy = y + i * lineH;
    slide.shapes.add({ geometry: "ellipse", position: { left: x, top: yy + 11, width: 8, height: 8 }, fill: opts.dot ?? C.blue, line: { style: "solid", fill: opts.dot ?? C.blue, width: 0 } });
    addText(slide, item, x + 20, yy, w - 20, lineH - 2, { fontSize: opts.fontSize ?? 18, color: opts.color ?? C.text, valign: "middle" });
  });
}

// 1. Title
{
  const s = presentation.slides.add();
  s.background.fill = C.white;
  addBox(s, 0, 0, 1280, 720, { geometry: "rect", fill: C.white, line: C.white, radius: "none" });
  addBox(s, 0, 0, 22, 720, { geometry: "rect", fill: C.navy, line: C.navy, radius: "none" });
  addText(s, "市场需求落实与评测汇报", 86, 168, 1050, 82, { fontSize: 54, bold: true, color: C.ink });
  addText(s, "无人远程火力打击装备能力图像挖掘", 88, 268, 900, 44, { fontSize: 26, color: C.blue });
  addRule(s, 88, 338, 180, C.blue, 4);
  addText(s, "需求落实｜Benchmark 测试思路与结果｜消融实验设计与结果", 88, 370, 1000, 42, { fontSize: 21, color: C.text });
  addText(s, "汇报日期：2026年7月29日", 88, 598, 500, 28, { fontSize: 16, color: C.muted });
  addNotes(s, ["/Users/wangchen/equipment research/市场需求query及模板V2.docx"]);
}

// 2. Executive summary
{
  const s = presentation.slides.add();
  addHeader(s, "核心结论：需求合同已落地，方法有效性得到初步验证", "EXECUTIVE SUMMARY", 2);
  const cards = [
    ["需求落实", "三层九项报告、五判据审计、证据门控与九字段能力画像已进入生产主链", C.blue],
    ["Benchmark", "20条问题真实盲评：相对通用检索基线取得15胜3平2负，得分率82.5%", C.green],
    ["消融结论", "去除制胜机理后，完整方法7胜1平0负；核心链路贡献得到支持", C.amber],
  ];
  cards.forEach((c, i) => {
    const x = 72 + i * 382;
    addBox(s, x, 166, 350, 220, { fill: C.white, line: C.line, shadow: "shadow-sm" });
    addBox(s, x, 166, 8, 220, { geometry: "rect", fill: c[2], line: c[2], radius: "none" });
    addText(s, c[0], x + 28, 190, 280, 34, { fontSize: 24, bold: true, color: C.ink });
    addText(s, c[1], x + 28, 238, 292, 112, { fontSize: 18, color: C.text, valign: "top" });
  });
  addBox(s, 72, 426, 1136, 172, { fill: C.light, line: C.light });
  addText(s, "需要正视的短板", 96, 448, 260, 30, { fontSize: 22, bold: true, color: C.red });
  bulletList(s, [
    "相对通用Agent，事实与引用维度仅16票领先、50票落后、14票持平，证据绑定仍是首要优化项",
    "Benchmark完整方法平均耗时约22.9分钟，明显高于通用Agent约3.0分钟，需要持续优化质量—时延平衡",
    "去多源基线消融仅为方向性证据；8条样本、历史运行绑定，尚不足以形成统计性定论",
  ], 96, 488, 1060, 36, { fontSize: 17, dot: C.red });
  addNotes(s, [
    "/Users/wangchen/equipment research/outputs/evals/web-benchmark-20260729-082159/summary.json",
    "/Users/wangchen/equipment research/outputs/evals/ablations/ablation-20260729-142922/ablation-report.md",
    "/Users/wangchen/equipment research/outputs/runs/run-a4106237-6032-4a8a-b0c8-70f68ffef540/architecture-acceptance.json",
  ]);
}

// 3. Requirement decomposition
{
  const s = presentation.slides.add();
  addHeader(s, "原始需求被拆解为四类可验收能力", "01 REQUIREMENT DECOMPOSITION", 3);
  const rows = [
    ["研究范围", "无人远程火力打击；体系化、实战化、智能化、颠覆化；兼顾通用化与规模化"],
    ["问题空间", "正向扫描、局部战争、国际形势、潜在场景、技术革命、作战任务、新质毁伤"],
    ["颠覆逻辑", "成本、平台、时间、毁伤、体系、伦理与博弈六个维度，支持继续发散"],
    ["交付与验收", "三层九项报告；领域符合性、能力图像、制胜效能、创新性、可实现性五项评估"],
  ];
  rows.forEach((r, i) => {
    const y = 158 + i * 112;
    addBox(s, 72, y, 1136, 90, { fill: i % 2 === 0 ? C.light : C.white, line: C.line, radius: "rounded-md" });
    addText(s, r[0], 96, y + 16, 190, 56, { fontSize: 22, bold: true, color: C.navy });
    addText(s, r[1], 298, y + 12, 870, 64, { fontSize: 18, color: C.text });
  });
  addNotes(s, ["/Users/wangchen/equipment research/市场需求query及模板V2.docx"]);
}

// 4. Implementation mapping
{
  const s = presentation.slides.add();
  addHeader(s, "需求落实已形成“输入—研究—推理—交付—审计”闭环", "02 IMPLEMENTATION STATUS", 4);
  const cols = [72, 280, 580, 940];
  ["需求项", "系统落实", "证据产物", "状态"].forEach((t, i) => addText(s, t, cols[i] + 10, 154, [190, 280, 340, 150][i], 38, { fontSize: 17, bold: true, color: C.white, align: i === 3 ? "center" : "left" }));
  addBox(s, 72, 146, 1136, 48, { geometry: "rect", fill: C.navy, line: C.navy, radius: "none" });
  // redraw header above box for z-order
  ["需求项", "系统落实", "证据产物", "状态"].forEach((t, i) => addText(s, t, cols[i] + 10, 151, [190, 280, 340, 150][i], 38, { fontSize: 17, bold: true, color: C.white, align: i === 3 ? "center" : "left" }));
  const data = [
    ["多维需求扫描", "A–H驱动识别 + 三条研究路线 + 动态Agent选择", "discovery_blueprint / agent_sessions", "已落实", "done"],
    ["全链条制胜机理", "S1–S6推理 + L1/L2/L3门控 + 定向Recall", "reasoning_traceability / checkpoints", "已落实", "done"],
    ["三层九项模板", "固定标题、九项完整性校验、质量门禁", "report.md / report_quality_gate", "已落实", "done"],
    ["五项效果评估", "五判据审计 + 八维盲评Rubric", "architecture-acceptance / judgments", "已落实", "done"],
    ["规模化长期记忆", "材料化证据、索引、持久化与恢复已具备；跨任务知识沉淀仍需强化", "artifacts / run.db / knowledge index", "部分落实", "partial"],
  ];
  data.forEach((r, i) => {
    const y = 194 + i * 84;
    addBox(s, 72, y, 1136, 84, { geometry: "rect", fill: i % 2 ? C.white : C.light, line: C.line, radius: "none" });
    addText(s, r[0], 84, y + 10, 182, 64, { fontSize: 17, bold: true, color: C.ink });
    addText(s, r[1], 290, y + 8, 274, 66, { fontSize: 16, color: C.text });
    addText(s, r[2], 590, y + 8, 330, 66, { fontSize: 15, color: C.muted });
    statusTag(s, 970, y + 27, r[3], r[4]);
  });
  addNotes(s, [
    "/Users/wangchen/equipment research/README.md",
    "/Users/wangchen/equipment research/configs/equipment_deep_research/harness.yaml",
    "/Users/wangchen/equipment research/outputs/runs/run-a4106237-6032-4a8a-b0c8-70f68ffef540/architecture-acceptance.json",
  ]);
}

// 5. Workflow
{
  const s = presentation.slides.add();
  addHeader(s, "系统把开放式问题转化为可追溯的装备能力图像", "02 IMPLEMENTATION STATUS", 5);
  const stages = [
    ["1", "任务解析", "识别场景、路线、约束与交付合同"],
    ["2", "多源研究", "场景、装备、运用、技术等专业智能体分工"],
    ["3", "制胜推理", "S1–S6将事实转化为机制、能力与差距"],
    ["4", "报告生成", "三层九项 + 九字段能力画像 + 验证矩阵"],
    ["5", "门控审计", "证据、覆盖、创新、可行性与限制说明"],
  ];
  stages.forEach((st, i) => {
    const x = 72 + i * 226;
    addBox(s, x, 190, 196, 250, { fill: i === 2 ? C.paleBlue : C.white, line: i === 2 ? C.blue : C.line, shadow: "shadow-sm" });
    addBox(s, x + 20, 212, 42, 42, { geometry: "ellipse", fill: i === 2 ? C.blue : C.navy, line: i === 2 ? C.blue : C.navy });
    addText(s, st[0], x + 20, 212, 42, 42, { fontSize: 20, bold: true, color: C.white, align: "center" });
    addText(s, st[1], x + 20, 278, 156, 36, { fontSize: 23, bold: true, color: C.ink });
    addText(s, st[2], x + 20, 326, 156, 84, { fontSize: 16, color: C.text, valign: "top" });
    if (i < 4) addText(s, "→", x + 196, 292, 30, 40, { fontSize: 28, bold: true, color: C.blue, align: "center" });
  });
  addBox(s, 160, 492, 960, 92, { fill: C.light, line: C.light });
  addText(s, "关键设计原则", 184, 512, 170, 42, { fontSize: 20, bold: true, color: C.navy });
  addText(s, "不以一次生成代替研究：每项结论都应能回溯到 Query、证据、Agent Packet、推理步骤与能力条目。", 356, 506, 720, 54, { fontSize: 18, color: C.text });
  addNotes(s, [
    "/Users/wangchen/equipment research/docs/AGENT_ARCHITECTURE_IMPLEMENTATION.md",
    "/Users/wangchen/equipment research/outputs/runs/run-a4106237-6032-4a8a-b0c8-70f68ffef540/reasoning_traceability.json",
  ]);
}

// 6. Output contract
{
  const s = presentation.slides.add();
  addHeader(s, "三层九项模板已转化为强制输出合同与质量门禁", "02 IMPLEMENTATION STATUS", 6);
  const layers = [
    ["第一层 需求挖掘", ["① 典型作战场景", "② 新战法/技术与制胜机理", "③ 装备能力特征与指标方向"], C.paleBlue, C.blue],
    ["第二层 技术攻关", ["④ 实现途径：改进/集成/突破", "⑤ 核心技术、成熟度与优先级", "⑥ 技术耦合与卡点风险"], C.paleAmber, C.amber],
    ["第三层 能力与效能", ["⑦ 能力域、指标画像与谱系位置", "⑧ 补链/强链/开链效能贡献", "⑨ 优先级与演示验证抓手"], C.paleGreen, C.green],
  ];
  layers.forEach((l, i) => {
    const x = 72 + i * 382;
    addBox(s, x, 158, 350, 324, { fill: l[2], line: l[3] });
    addText(s, l[0], x + 24, 182, 302, 40, { fontSize: 23, bold: true, color: l[3] });
    bulletList(s, l[1], x + 26, 246, 300, 64, { fontSize: 17, dot: l[3] });
  });
  addText(s, "最终审计：领域符合性｜装备能力图像｜制胜效能｜创新性｜可实现性/成熟度", 104, 526, 1072, 38, { fontSize: 20, bold: true, color: C.navy, align: "center" });
  addText(s, "系统对标题顺序、九项实质内容、事实/推断边界、定量指标来源与验证条件进行自动检查。", 104, 570, 1072, 34, { fontSize: 17, color: C.text, align: "center" });
  addNotes(s, [
    "/Users/wangchen/equipment research/市场需求query及模板V2.docx",
    "/Users/wangchen/equipment research/src/equipment_deep_research/agents/provider.py",
    "/Users/wangchen/equipment research/outputs/runs/run-a4106237-6032-4a8a-b0c8-70f68ffef540/report.md",
  ]);
}

// 7. Benchmark design
{
  const s = presentation.slides.add();
  addHeader(s, "Benchmark采用真实Query、强基线与双盲成对评审", "03 BENCHMARK DESIGN", 7);
  const top = [
    ["数据集", "战术精打前沿方向50条；本轮选择前20条问题"],
    ["对照系统", "完整方法 vs 通用检索Agent、纯LLM、智谱LLM"],
    ["评审机制", "2名GPT-5.5评审 × A/B与B/A双顺序；系统身份隐藏"],
    ["运行规模", "4系统 × 20条 = 80份回答；120个盲评Pair；0个评审错误"],
  ];
  top.forEach((r, i) => {
    const x = 72 + (i % 2) * 574;
    const y = 158 + Math.floor(i / 2) * 126;
    addBox(s, x, y, 546, 102, { fill: i % 2 ? C.white : C.light, line: C.line });
    addText(s, r[0], x + 22, y + 16, 120, 30, { fontSize: 20, bold: true, color: C.navy });
    addText(s, r[1], x + 146, y + 12, 374, 72, { fontSize: 17, color: C.text });
  });
  addBox(s, 72, 430, 1136, 178, { fill: C.paleBlue, line: C.paleBlue });
  addText(s, "公平性控制", 96, 450, 170, 32, { fontSize: 21, bold: true, color: C.blue });
  bulletList(s, [
    "各基线接收同一份三层九项交付任务书，但不泄露项目内部A–H、S1–S6等方法信息",
    "通用Agent在隔离工作区运行并允许联网检索；纯LLM基线明确禁止浏览和虚构来源",
    "公开Pair仅含Query与匿名回答；系统映射单独保存在管理文件中",
  ], 96, 488, 1060, 32, { fontSize: 15, dot: C.blue });
  addNotes(s, [
    "/Users/wangchen/equipment research/evals/README.md",
    "/Users/wangchen/equipment research/outputs/evals/web-benchmark-20260729-082159/web-run.json",
  ]);
}

// 8. Evaluation criteria
{
  const s = presentation.slides.add();
  addHeader(s, "评测标准把文档五项要求细化为八个可判别维度", "03 BENCHMARK DESIGN", 8);
  const dims = [
    ["领域符合性", "路线任务完成度｜军事运用价值"],
    ["能力图像", "能力映射与需求质量｜跨场景体系鲁棒性"],
    ["制胜效能", "因果与机理深度｜军事运用价值"],
    ["创新性", "新颖性与前瞻性"],
    ["可实现性", "事实与证据｜不确定性与验证"],
  ];
  dims.forEach((d, i) => {
    const y = 154 + i * 90;
    addBox(s, 72, y, 240, 68, { fill: C.navy, line: C.navy, radius: "rounded-md" });
    addText(s, d[0], 72, y, 240, 68, { fontSize: 21, bold: true, color: C.white, align: "center" });
    addText(s, d[1], 346, y, 700, 68, { fontSize: 19, color: C.text });
    addText(s, i < 4 ? "质量维度" : "可信边界", 1060, y, 120, 68, { fontSize: 15, bold: true, color: i < 4 ? C.blue : C.amber, align: "center" });
  });
  addText(s, "判定规则：逐维投票 + 总体胜负；同时记录硬失败、引用问题、置信度和需仲裁样本。", 96, 620, 1088, 34, { fontSize: 17, color: C.muted, align: "center" });
  addNotes(s, [
    "/Users/wangchen/equipment research/市场需求query及模板V2.docx",
    "/Users/wangchen/equipment research/outputs/evals/web-benchmark-20260729-082159/pairwise_prompt.md",
  ]);
}

// 9. Benchmark results
{
  const s = presentation.slides.add();
  addHeader(s, "完整方法在三类基线上均取得显著总体优势", "04 BENCHMARK RESULTS", 9);
  s.charts.add("bar", {
    position: { left: 72, top: 166, width: 720, height: 382 },
    categories: ["通用检索Agent", "纯LLM", "智谱LLM"],
    series: [{ name: "完整方法得分率", values: [82.5, 97.5, 97.5], fill: C.blue }],
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 50 },
    hasLegend: false,
    xAxis: { min: 0, max: 100, majorUnit: 20, numberFormatCode: "0\"%\"", majorGridlines: { style: "solid", fill: C.line, width: 1 }, textStyle: { fill: C.muted, fontSize: 13 } },
    yAxis: { textStyle: { fill: C.text, fontSize: 15 }, line: { style: "solid", fill: C.line, width: 1 } },
    dataLabels: { showValue: true, position: "outEnd", textStyle: { fill: C.ink, fontSize: 15, bold: true } },
    chartFill: C.white,
    plotAreaFill: C.white,
  });
  const stats = [
    ["vs 通用Agent", "15胜 3平 2负", "95%区间 65%–95%"],
    ["vs 纯LLM", "19胜 1平 0负", "95%区间 92.5%–100%"],
    ["vs 智谱LLM", "19胜 1平 0负", "95%区间 92.5%–100%"],
  ];
  stats.forEach((r, i) => {
    const y = 166 + i * 124;
    addBox(s, 842, y, 366, 98, { fill: i === 0 ? C.paleBlue : C.light, line: i === 0 ? C.blue : C.line });
    addText(s, r[0], 864, y + 12, 156, 30, { fontSize: 18, bold: true, color: C.navy });
    addText(s, r[1], 1020, y + 10, 166, 34, { fontSize: 19, bold: true, color: C.green, align: "right" });
    addText(s, r[2], 864, y + 52, 322, 26, { fontSize: 14, color: C.muted });
  });
  addText(s, "口径：得分率 = 胜 + 0.5×平；20条Query，双评审双顺序。", 72, 588, 760, 26, { fontSize: 15, color: C.muted });
  addNotes(s, ["/Users/wangchen/equipment research/outputs/evals/web-benchmark-20260729-082159/summary.json"]);
}

// 10. Strongest baseline dimensions
{
  const s = presentation.slides.add();
  addHeader(s, "相对最强基线，方法优势集中在机理、能力映射与前瞻性", "04 BENCHMARK RESULTS", 10);
  const dims = ["任务完成", "事实证据", "因果机理", "能力映射", "不确定性", "军事价值", "前瞻性", "体系鲁棒"],
    full = [65, 16, 68, 69, 60, 69, 71, 66],
    base = [13, 50, 12, 10, 16, 11, 4, 12];
  s.charts.add("bar", {
    position: { left: 72, top: 154, width: 836, height: 442 },
    categories: dims,
    series: [
      { name: "完整方法", values: full, fill: C.blue },
      { name: "通用Agent", values: base, fill: "#AAB8C6" },
    ],
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 35 },
    hasLegend: true,
    legend: { position: "bottom", textStyle: { fill: C.text, fontSize: 13 } },
    xAxis: { min: 0, max: 80, majorUnit: 20, majorGridlines: { style: "solid", fill: C.line, width: 1 }, textStyle: { fill: C.muted, fontSize: 12 } },
    yAxis: { textStyle: { fill: C.text, fontSize: 13 }, line: { style: "solid", fill: C.line, width: 1 } },
    chartFill: C.white,
    plotAreaFill: C.white,
  });
  addBox(s, 948, 174, 260, 174, { fill: C.paleGreen, line: C.green });
  addText(s, "优势", 970, 194, 100, 30, { fontSize: 21, bold: true, color: C.green });
  addText(s, "能力映射 69:10\n军事价值 69:11\n前瞻性 71:4", 970, 234, 210, 92, { fontSize: 18, color: C.text, valign: "top" });
  addBox(s, 948, 374, 260, 174, { fill: "#FBEDEC", line: C.red });
  addText(s, "短板", 970, 394, 100, 30, { fontSize: 21, bold: true, color: C.red });
  addText(s, "事实证据 16:50\n另有14票持平\n需强化正文—证据逐条绑定", 970, 434, 210, 92, { fontSize: 17, color: C.text, valign: "top" });
  addNotes(s, ["/Users/wangchen/equipment research/outputs/evals/web-benchmark-20260729-082159/summary.json"]);
}

// 11. Efficiency
{
  const s = presentation.slides.add();
  addHeader(s, "质量提升伴随明显时延成本，下一阶段需优化质量—效率前沿", "04 BENCHMARK RESULTS", 11);
  const systems = [
    ["完整方法", 22.9, "14.3个来源/条", C.blue],
    ["通用Agent", 3.0, "11.8个来源/条", C.green],
    ["纯LLM", 2.5, "无联网来源", C.amber],
    ["智谱LLM", 0.8, "无联网来源", "#8B6FAE"],
  ];
  systems.forEach((r, i) => {
    const y = 166 + i * 92;
    addText(s, r[0], 72, y, 150, 40, { fontSize: 18, bold: true, color: C.ink });
    addBox(s, 230, y + 5, Math.max(38, r[1] * 29), 28, { geometry: "rect", fill: r[3], line: r[3], radius: "none" });
    addText(s, `${r[1].toFixed(1)} 分钟`, 230 + Math.max(38, r[1] * 29) + 14, y, 110, 38, { fontSize: 17, bold: true, color: r[3] });
    addText(s, r[2], 1030, y, 170, 38, { fontSize: 15, color: C.muted, align: "right" });
  });
  addBox(s, 72, 558, 1136, 62, { fill: C.light, line: C.light });
  addText(s, "建议优化目标：在不降低五项审计门槛的前提下，将完整方法P50时延压缩至15分钟以内，并提升正式证据绑定率。", 92, 570, 1096, 38, { fontSize: 17, color: C.navy, align: "center" });
  addNotes(s, [
    "/Users/wangchen/equipment research/outputs/evals/web-benchmark-20260729-082159/summary.json",
    "/Users/wangchen/equipment research/outputs/evals/web-benchmark-20260729-082159/results.jsonl",
  ], "15分钟为汇报建议目标，并非当前实测结果。");
}

// 12. Ablation design
{
  const s = presentation.slides.add();
  addHeader(s, "消融实验分别验证“多源研究”和“制胜机理”两项核心设计", "05 ABLATION DESIGN", 12);
  const groups = [
    ["完整方法", "多角色、多通道", "S1–S6", "L1–L4启用", C.paleGreen, C.green],
    ["去多源基线", "单通用Agent、单通道", "单次S1–S6", "循环关闭", C.paleAmber, C.amber],
    ["去制胜机理", "完整多源基线", "跳过", "循环关闭", "#FBEDEC", C.red],
  ];
  groups.forEach((g, i) => {
    const y = 164 + i * 118;
    addBox(s, 72, y, 1136, 92, { fill: g[4], line: g[5] });
    addText(s, g[0], 96, y + 18, 200, 52, { fontSize: 22, bold: true, color: g[5] });
    addText(s, g[1], 330, y + 18, 250, 52, { fontSize: 18, color: C.text });
    addText(s, g[2], 620, y + 18, 180, 52, { fontSize: 18, color: C.text });
    addText(s, g[3], 850, y + 18, 250, 52, { fontSize: 18, color: C.text });
  });
  addText(s, "实验控制", 72, 548, 160, 30, { fontSize: 21, bold: true, color: C.navy });
  addText(s, "8条Query｜真实模式｜相同盲评规则｜检查被禁用阶段是否仍产生事件｜Bootstrap区间用于约束结论强度", 236, 544, 972, 42, { fontSize: 17, color: C.text });
  addNotes(s, [
    "/Users/wangchen/equipment research/outputs/evals/ablations/ablation-20260729-142922/manifest.json",
    "/Users/wangchen/equipment research/outputs/evals/ablations/ablation-20260729-142922/ablation-report.md",
  ]);
}

// 13. Ablation results
{
  const s = presentation.slides.add();
  addHeader(s, "制胜机理贡献明确；多源研究目前仅显示方向性收益", "05 ABLATION RESULTS", 13);
  s.charts.add("bar", {
    position: { left: 72, top: 166, width: 672, height: 330 },
    categories: ["去多源基线", "去制胜机理"],
    series: [{ name: "完整方法得分率", values: [62.5, 93.75], fill: C.blue }],
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 55 },
    hasLegend: false,
    xAxis: { min: 0, max: 100, majorUnit: 20, numberFormatCode: "0\"%\"", majorGridlines: { style: "solid", fill: C.line, width: 1 }, textStyle: { fill: C.muted, fontSize: 13 } },
    yAxis: { textStyle: { fill: C.text, fontSize: 15 } },
    dataLabels: { showValue: true, position: "outEnd", textStyle: { fill: C.ink, fontSize: 15, bold: true } },
    chartFill: C.white,
    plotAreaFill: C.white,
  });
  addBox(s, 796, 166, 412, 148, { fill: C.paleAmber, line: C.amber });
  addText(s, "去多源基线", 820, 184, 180, 30, { fontSize: 20, bold: true, color: C.amber });
  addText(s, "5胜0平3负｜得分率62.5%\n95%配对区间跨0，仅能报告方向性证据", 820, 226, 350, 66, { fontSize: 17, color: C.text, valign: "top" });
  addBox(s, 796, 338, 412, 148, { fill: C.paleGreen, line: C.green });
  addText(s, "去制胜机理", 820, 356, 180, 30, { fontSize: 20, bold: true, color: C.green });
  addText(s, "7胜1平0负｜得分率93.8%\n95%配对区间[62.5%,100%]，设计贡献得到支持", 820, 398, 350, 66, { fontSize: 17, color: C.text, valign: "top" });
  addBox(s, 72, 538, 1136, 76, { fill: C.light, line: C.light });
  addText(s, "解释：S1–S6制胜链是当前质量跃升的主要来源；多源Agent的独立增益需要扩大样本并严格同版本重跑。", 94, 552, 1092, 48, { fontSize: 18, bold: true, color: C.navy, align: "center" });
  addNotes(s, ["/Users/wangchen/equipment research/outputs/evals/ablations/ablation-20260729-142922/ablation-report.md"]);
}

// 14. Next steps
{
  const s = presentation.slides.add();
  addHeader(s, "下一阶段聚焦证据闭环、规模验证与效率优化", "06 NEXT STEPS", 14);
  const actions = [
    ["P0", "强化证据绑定", "正文关键结论逐条绑定正式Evidence ID；消除“证据卡未登记/需核验”的残留输出", C.red],
    ["P0", "扩大Benchmark", "从20条扩至50条全量；加入专家人工抽检与跨评审模型一致性检查", C.red],
    ["P1", "严格重跑消融", "同模型、同时间窗、同配置独立执行；增加去反馈循环、去证据门控等组别", C.amber],
    ["P1", "优化时延成本", "并发检索、增量搜索、上下文裁剪、局部恢复；建立质量—耗时Pareto看板", C.amber],
    ["P2", "深化需求覆盖", "围绕文档12类分类提问和6类颠覆逻辑建立分层覆盖率与缺口清单", C.blue],
  ];
  actions.forEach((a, i) => {
    const y = 154 + i * 88;
    addBox(s, 72, y, 76, 58, { fill: a[3], line: a[3], radius: "rounded-md" });
    addText(s, a[0], 72, y, 76, 58, { fontSize: 18, bold: true, color: C.white, align: "center" });
    addText(s, a[1], 174, y, 240, 58, { fontSize: 20, bold: true, color: C.ink });
    addText(s, a[2], 426, y, 756, 58, { fontSize: 17, color: C.text });
  });
  addBox(s, 72, 610, 1136, 42, { fill: C.navy, line: C.navy, radius: "rounded-md" });
  addText(s, "建议决策：批准进入“证据质量专项 + 50条全量Benchmark + 同版本消融复测”阶段。", 86, 610, 1108, 42, { fontSize: 18, bold: true, color: C.white, align: "center" });
  addNotes(s, [
    "/Users/wangchen/equipment research/outputs/evals/web-benchmark-20260729-082159/summary.json",
    "/Users/wangchen/equipment research/outputs/evals/ablations/ablation-20260729-142922/ablation-report.md",
    "/Users/wangchen/equipment research/市场需求query及模板V2.docx",
  ]);
}

await fs.mkdir(PREVIEW_DIR, { recursive: true });
for (const [index, slide] of presentation.slides.items.entries()) {
  const stem = `slide-${String(index + 1).padStart(2, "0")}`;
  await writeBlob(`${PREVIEW_DIR}/${stem}.png`, await presentation.export({ slide, format: "png", scale: 1 }));
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(`${PREVIEW_DIR}/${stem}.layout.json`, await layout.text());
}
await writeBlob(`${PREVIEW_DIR}/deck-montage.webp`, await presentation.export({ format: "webp", montage: true, scale: 1 }));
const pptx = await PresentationFile.exportPptx(presentation);
await pptx.save(OUT);
console.log(OUT);
