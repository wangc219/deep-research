/**
 * Column-scoped deep research over a bound capability card.
 *
 * The launcher used to seed every directed session with the same instruction:
 * treat the card as a seed and rewrite it into some other disruptive weapon.
 * That makes the one thing a reader usually wants — drilling further into the
 * card actually in front of them — the hardest thing to ask for.  These
 * helpers turn each of the five authored columns into its own research target.
 */
const text = (value) => String(value ?? "").trim();

/** Canonical order of the five columns a S6 capability card is authored in. */
export const PORTRAIT_SECTION_ORDER = [
  "概述",
  "装备与技术实现",
  "关键作战流程",
  "形成能力与作战效果",
  "制胜逻辑机理",
];

const SECTION_ALIASES = new Map([
  ["制胜逻辑机理与对抗边界", "制胜逻辑机理"],
  ["制胜逻辑", "制胜逻辑机理"],
  ["能力画像概述", "概述"],
]);

const SECTION_ASKS = {
  概述: "把概述收紧为一条可验证的作战定位：明确打击对象、典型使用场景与不可替代之处，去掉泛化修辞。",
  装备与技术实现:
    "逐层展开构型与关键技术：分系统组成、核心指标区间、技术成熟度与主要工程瓶颈，并分别标注哪些是有据可依的事实、哪些是推断。",
  关键作战流程:
    "把作战流程还原为可执行时序：发现、决策、进入、命中、毁伤评估各步的时间窗口、前置依赖与失败分支。",
  形成能力与作战效果:
    "量化作战效果：给出可观察的毁伤指标、任务失能判据、效果保持时间，并说明在什么条件下效果会显著退化。",
  制胜逻辑机理:
    "拆解制胜机理与对抗边界：为什么对手难以低成本化解，以及在哪些条件下该机理会失效。",
};

const SECTION_HINTS = {
  概述: "收紧作战定位",
  装备与技术实现: "展开构型与瓶颈",
  关键作战流程: "还原作战时序",
  形成能力与作战效果: "量化毁伤与判据",
  制胜逻辑机理: "拆解机理与边界",
};

export const portraitSectionLabel = (label) =>
  SECTION_ALIASES.get(text(label)) || text(label);

const PARSEABLE_LABELS = [
  "概述",
  "装备与技术实现",
  "关键作战流程",
  "形成能力与作战效果",
  "制胜逻辑机理与对抗边界",
  "制胜逻辑机理",
  "制胜逻辑",
  "发展与验证路径",
  "决策与考核口径",
];

/**
 * Split an authored portrait blob into its labelled columns.  The workbench
 * has a stricter parser that also strips schema leakage; this one exists so
 * the platform shell can read a stored card without importing the React app.
 */
export function parsePortraitSections(value) {
  const normalized = text(value).replace(/\r/g, "").replace(/\s+/g, " ");
  if (!normalized) return [];
  const matches = [
    ...normalized.matchAll(
      new RegExp(`(${PARSEABLE_LABELS.join("|")})\\s*[：:]`, "g"),
    ),
  ];
  if (!matches.length)
    return normalizePortraitSections([{ label: "概述", text: normalized }]);
  const rows = matches.map((match, index) => ({
    label: match[1],
    text: normalized.slice(
      match.index + match[0].length,
      matches[index + 1]?.index ?? normalized.length,
    ),
  }));
  const lead = normalized
    .slice(0, matches[0].index)
    .replace(/^[-*•]\s*/, "")
    .trim();
  return normalizePortraitSections(
    lead ? [{ label: "概述", text: lead }, ...rows] : rows,
  );
}
export const portraitSectionHint = (label) =>
  SECTION_HINTS[portraitSectionLabel(label)] || "继续深挖本栏";

/** Normalize an injected card portrait into ordered, de-duplicated columns. */
export function normalizePortraitSections(value, { clip = 1200 } = {}) {
  const rows = Array.isArray(value) ? value : [];
  const merged = new Map();
  for (const row of rows) {
    const label = portraitSectionLabel(row?.label);
    const body = text(row?.text).replace(/\s+/g, " ");
    if (!label || !body || merged.has(label)) continue;
    merged.set(label, body.slice(0, clip));
  }
  const ordered = PORTRAIT_SECTION_ORDER.filter((label) => merged.has(label));
  const extra = [...merged.keys()].filter(
    (label) => !PORTRAIT_SECTION_ORDER.includes(label),
  );
  return [...ordered, ...extra].map((label) => ({
    label,
    text: merged.get(label),
  }));
}

/**
 * Compact digest of the bound card, safe to embed in a seed or turn prompt.
 * `budget` is the total character allowance; the server rejects a focus longer
 * than 1600, so the per-column clip is derived from what is actually left.
 */
export function portraitSectionDigest(sections, { budget = 1300 } = {}) {
  const rows = normalizePortraitSections(sections);
  if (!rows.length) return "";
  const clip = Math.max(80, Math.floor(budget / rows.length) - 12);
  return rows
    .map((item) => `【${item.label}】${item.text.slice(0, clip)}`)
    .join("\n");
}

/** One turn that deepens a single column without diverging off the card. */
export function portraitSectionPrompt(label, equipment = "", body = "") {
  const section = portraitSectionLabel(label);
  if (!section) return "";
  const ask =
    SECTION_ASKS[section] ||
    `围绕「${section}」继续深挖，给出更具体、可核验的结论。`;
  const target = text(equipment) ? `「${text(equipment)}」` : "当前装备";
  const current = text(body)
    ? `\n本栏现有内容：${text(body).slice(0, 600)}`
    : "";
  return `仅针对${target}的「${section}」一栏继续深挖，不要改成其他装备方向。${ask}${current}\n请指出其中仍不成立或证据不足的部分，并给出下一步核验动作。`;
}

/**
 * Seed instruction for a session opened from a capability card.  It states the
 * card's current five columns up front so the first turn already argues from
 * them, and it leaves both directions open: deepen a column, or diverge.
 */
export function capabilitySeedFocus(
  equipment,
  sections,
  { limit = 1560 } = {},
) {
  const target = text(equipment) || "当前装备";
  const header = `以已有能力画像卡「${target}」为启发基线，面向关联 Query 场景及未来战争态势开放发散新质创新颠覆武器装备。`;
  const rules = [
    "能力画像及其五栏只提供已知起点、待突破假设和对照坐标，不得成为候选边界。",
    "围绕未来战争中的制胜与制衡对手，从任务链反转、作用机理、装备构型、交战窗口、成本交换和反适应等维度探索正交方向。",
    "不预设单一装备形态、技术路线或固定结论；先扩大解空间，再按作战价值、颠覆性与可行性收敛。",
    "结论保持在装备概念与能力画像层，区分事实、推断和待核验项。",
  ]
    .map((item, index) => `${index + 1}. ${item}`)
    .join("\n");
  const frame = `${header}\n\n当前五栏：\n{digest}\n\n研究要求：\n${rules}`;
  const digest = portraitSectionDigest(sections, {
    budget: limit - frame.length + "{digest}".length,
  });
  if (!digest) return `${header}\n\n研究要求：\n${rules}`.slice(0, limit);
  return frame.replace("{digest}", digest).slice(0, limit);
}

/** Opening suggestions for a card-bound session, replacing the generic pool. */
export function capabilityWelcomeSuggestions(equipment, sections, count = 4) {
  const rows = normalizePortraitSections(sections);
  if (!rows.length) return [];
  return rows
    .slice(0, count)
    .map((item) => portraitSectionPrompt(item.label, equipment, item.text));
}
