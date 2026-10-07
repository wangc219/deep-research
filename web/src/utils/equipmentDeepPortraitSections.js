/**
 * Column-scoped deep research over a bound capability card.
 *
 * The launcher used to seed every directed session with the same instruction:
 * treat the card as a seed and rewrite it into some other disruptive weapon.
 * That makes the one thing a reader usually wants — drilling further into the
 * card actually in front of them — the hardest thing to ask for.  These
 * helpers turn each of the five authored columns into its own research target.
 */
const text = (value) => String(value ?? '').trim()

export const TECHNOLOGY_CABIN_SECTION = '装备与技术实现'
export const TECHNOLOGY_SOLUTION_TRIGGER = '请形成一份可交付的技术实现方案'
export const WEAPON_SCHEME_AGENT_SLUG = 'weapon-equipment-scheme'
export const CAPABILITY_PORTRAIT_AGENT_SLUG = 'equipment-capability-portrait'

export const TECHNOLOGY_SOLUTION_CHAPTERS = [
  {
    title: '能力目标',
    question: '要形成什么能力',
    scope: '作战对象、任务场景、能力边界、效能指标、约束条件与验收判据'
  },
  {
    title: '装备总体设计',
    question: '装备总体怎么设计',
    scope: '系统架构、总体构型、功能组成、模块划分、工作模式与接口关系'
  },
  {
    title: '技术体系',
    question: '主要依靠哪些技术',
    scope: '核心技术、支撑技术、基础技术、关键部件技术及能力映射'
  },
  {
    title: '关键技术识别',
    question: '哪些技术最关键',
    scope: '关键度、牵引指标、依赖关系、成熟度、替代性与优先级'
  },
  {
    title: '突破难点',
    question: '哪些地方最难突破',
    scope: '瓶颈根因、理论或工程极限、耦合冲突、失效模式与突破判据'
  },
  {
    title: '解决路径',
    question: '有哪些解决路径',
    scope: '候选路线、原理抓手、收益代价、前置依赖、风险与路线决策门'
  },
  {
    title: '具体实现',
    question: '具体如何实现',
    scope: '原理、算法、结构、材料、器件、控制、软件、工艺、集成、试验与阶段交付'
  }
]

const technologySolutionOutline = () =>
  TECHNOLOGY_SOLUTION_CHAPTERS.map(
    ({ title, question, scope }, index) => `${index + 1}.${title}（回答“${question}”：${scope}）`
  ).join('；')

const technologyImplementationPlanPrompt = () =>
  `${TECHNOLOGY_SOLUTION_TRIGGER}，供一线研发人员直接拆任务、做样机和测指标。纠偏结论只作简短设计输入，正文必须以${technologySolutionOutline()}为七个一级章节，前一章结论必须成为后一章输入，形成“能力—设计—技术—关键项—难点—路径—实现”追溯链。每章落实到分系统、输入输出接口、指标与预算、负责人专业、阶段交付物和验收判据；具体实现章还须覆盖原理、算法、结构、材料、器件、控制、软件、工艺、集成顺序、样机阶段、WBS、试验矩阵、TRL跃迁、里程碑与决策门、风险/FMEA/降级策略，以及30/60/90天启动包。事实、工程判断和待验证参数必须分开；无可靠依据的数值标注“工程假设/TBD”，不得重复写成长篇纠错报告。若已有攻关任务书，应另建“研发与技术实现方案”交付物，不得覆盖原文件。`

export const TECHNOLOGY_CABIN_ACTIONS = [
  {
    id: 'capability_goal',
    label: '能力目标',
    hint: '明确场景、对象、指标边界与验收判据'
  },
  {
    id: 'overall_design',
    label: '总体设计',
    hint: '设计构型、分系统、工作模式和接口链路'
  },
  {
    id: 'technology_system',
    label: '技术体系',
    hint: '建立能力到核心、支撑和基础技术的映射'
  },
  {
    id: 'critical_technologies',
    label: '关键技术',
    hint: '按关键度、成熟度和不可替代性确定优先级'
  },
  {
    id: 'hardest_bottlenecks',
    label: '突破难点',
    hint: '定位极限、冲突、失效根因和突破判据'
  },
  {
    id: 'solution_routes',
    label: '解决路径',
    hint: '比较候选路线的收益、代价、风险与决策门'
  },
  {
    id: 'implementation_plan',
    label: '具体实现',
    hint: '形成可拆任务、做样机和测指标的完整方案',
    primary: true
  }
]

/** Canonical order of the five columns a S6 capability card is authored in. */
export const PORTRAIT_SECTION_ORDER = [
  '概述',
  '装备与技术实现',
  '关键作战流程',
  '形成能力与作战效果',
  '制胜逻辑机理'
]

export const S6_PORTRAIT_MODULE_KEYS = [
  'overview',
  'technology_implementation',
  'operational_process',
  'capability_effects',
  'winning_logic'
]

/** Canonical authoring request shared by all deep-conversation card actions. */
export function s6CapabilityCardPrompt(equipment = '当前装备', lead = '') {
  const target = text(equipment) || '当前装备'
  const purpose =
    text(lead) || '综合本次深研结论重写一版能力画像，保持装备身份、任务定位和已经收敛的作用机理一致'
  return `${purpose}。为「${target}」形成正式 S6 五栏能力卡：正文只能依次使用“概述、装备与技术实现、关键作战流程、形成能力与作战效果、制胜逻辑机理”五个精确栏名，不加“修订”等后缀，不增加第六栏。概述闭合场景、对象、定位和关键变化；技术栏写主路径、备选路径、构型、分系统、部件、接口与取舍；流程栏闭合主体、条件、动作、状态、异常和转段；效果栏区分新增任务、直接战果、体系收益、敌方代价与判据；制胜栏闭合旧规则、作用链、交换关系、对手经济反制及新增代价。先分别起草五栏，再逐栏检查职责、完整因果、长度和跨栏重复，发现短栏或缺口必须先补写。每栏以 360–400 个有效中文字为常规目标，复杂因果可略多，禁止硬切、机械凑字、重复栏和跨栏复用。五栏全部通过自检后，调用 save_equipment_capability_draft 新增待核验版本，并在 structured_fields 中同时提交 capability_portrait_modules 与 capability_card_draft，两者均使用 ${S6_PORTRAIT_MODULE_KEYS.join('、')} 五个键；不得覆盖正式卡。`
}

const SECTION_ALIASES = new Map([
  ['制胜逻辑机理与对抗边界', '制胜逻辑机理'],
  ['制胜逻辑', '制胜逻辑机理'],
  ['能力画像概述', '概述']
])

const SECTION_ASKS = {
  概述: '围绕装备定位继续发散补充：明确主要作战对象、典型场景、体系角色，以及技术实现、作战流程和制胜机理之间如何闭环。',
  装备与技术实现:
    '以武器研发为中心深挖：拆解分系统、关键技术卡点和工程痛点，分析卡点成因、指标耦合与依赖条件；为每个痛点提出可比较的攻关路线、关键试验、成熟度跃迁路径和取舍，不停留在技术名词罗列。',
  关键作战流程:
    '把作战流程推演为可执行链路：明确平台与人员角色、信息流和火力流、发现—决策—进入—作用—评估时序、协同接口、关键窗口和备选处置，并反推对技术实现的要求。',
  形成能力与作战效果:
    '从技术实现和作战流程推导能力形成过程：说明哪些关键技术组合产生何种能力、如何在任务链中兑现作战效果，以及可观察的效果指标和任务达成判据。',
  制胜逻辑机理:
    '围绕制胜逻辑做多路径深度发散：从作用链、信息优势、时空窗口、成本交换、体系增益和对手反适应等角度解释优势如何产生，并把每条机理反推到必要技术与作战动作。'
}

const SECTION_HINTS = {
  概述: '收紧作战定位',
  装备与技术实现: '展开构型与瓶颈',
  关键作战流程: '还原作战时序',
  形成能力与作战效果: '量化毁伤与判据',
  制胜逻辑机理: '拆解机理与边界'
}

export const portraitSectionLabel = (label) => SECTION_ALIASES.get(text(label)) || text(label)

export const isTechnologyCabinSection = (label) =>
  portraitSectionLabel(label) === TECHNOLOGY_CABIN_SECTION

const TECHNOLOGY_CABIN_TASKS = {
  mission: `围绕研发该装备所必需的核心技术开展攻关。先核验和纠偏，但纠偏只作为方案设计输入；随后必须把结论转化为研发方案，主体逐步覆盖${technologySolutionOutline()}。给出下一步应深挖的问题、攻关顺序和可验收交付物。`,
  capability_goal:
    '先回答要形成什么能力：锁定作战场景、目标对象、任务链位置、能力边界、核心效能指标与可测试的验收判据，区分期望效果和装备自身必须具备的能力。',
  overall_design:
    '由能力目标反推装备总体设计：给出总体构型、分系统和功能分配、工作模式、信号/能量/控制链、内外部接口及关键预算，说明每项设计怎样承接能力指标。',
  technology_system:
    '建立支撑总体设计的技术体系，区分核心技术、支撑技术、基础技术和关键部件技术；逐项标明所支撑的能力、所属分系统、输入输出、依赖条件与当前成熟度。',
  critical_technologies:
    '从技术体系中识别真正关键的技术，按能力牵引强度、系统瓶颈性、不可替代性、依赖传播范围和成熟度差距排序，说明不突破时哪项能力或总体设计会失败。',
  hardest_bottlenecks:
    '聚焦最难突破之处：拆解理论极限、材料与器件上限、算法与算力约束、环境适应、指标耦合、制造一致性和系统集成冲突，给出根因、失效模式及可量测的突破判据。',
  solution_routes:
    '针对最高优先级难点提出至少两条可比较解决路径，写清原理抓手、预期收益、前置依赖、工程代价、主要风险、替代关系、关键试验和继续/切换/停止的决策门。',
  implementation_plan: technologyImplementationPlanPrompt(),
  // 兼容已经缓存或保存在旧会话草稿中的动作标识。
  pain_points:
    '拆解最影响研制落地的技术痛点：说明现象、根因、指标耦合、前置依赖、失效模式和突破判据，并排出优先级。',
  breakthrough_routes:
    '针对最高优先级卡点设计可比较的攻关路线，写清原理、关键抓手、预期指标收益、依赖条件、工程代价、主要风险和选择依据。',
  engineering_plan:
    '把优先路线拆成一线研发可执行的工程实现：明确分系统、材料与器件、算法与软件、关键接口、工艺约束、集成顺序和阶段交付物；未知参数保留为待验证范围。',
  verification_plan:
    '为当前路线设计由原理样机到整机集成的验证路径，明确关键试验、工况、测量项、通过判据，以及试验失败后如何回改设计。',
  maturity_risk:
    '规划关键技术的 TRL 跃迁、阶段里程碑和风险收敛，明确预警指标、缓解动作、备选路线，以及继续、切换或停止攻关的决策门。',
  solution_blueprint: technologyImplementationPlanPrompt()
}

/** Specialized R&D prompt used by the technology breakthrough cabin. */
export function technologyCabinPrompt(equipment = '', body = '', action = 'mission') {
  const target = text(equipment) ? `「${text(equipment)}」` : '当前装备'
  const task = TECHNOLOGY_CABIN_TASKS[action] || TECHNOLOGY_CABIN_TASKS.mission
  const sourceRule = text(body)
    ? '原卡中的相关技术仅作为研究线索，不视为完整或正确答案，应主动补充遗漏并纠正概念化表述。'
    : '不要假定现有技术描述已经完整。'
  return `围绕${target}开展技术攻关，保持装备身份和任务定位不变。${sourceRule}${task}避免空泛罗列和无依据的精确参数。`
}

const PARSEABLE_LABELS = [
  '概述',
  '装备与技术实现',
  '关键作战流程',
  '形成能力与作战效果',
  '制胜逻辑机理与对抗边界',
  '制胜逻辑机理',
  '制胜逻辑',
  '发展与验证路径',
  '决策与考核口径'
]

/**
 * Split an authored portrait blob into its labelled columns.  The workbench
 * has a stricter parser that also strips schema leakage; this one exists so
 * the platform shell can read a stored card without importing the React app.
 */
export function parsePortraitSections(value) {
  const normalized = text(value).replace(/\r/g, '').replace(/\s+/g, ' ')
  if (!normalized) return []
  const matches = [
    ...normalized.matchAll(new RegExp(`(${PARSEABLE_LABELS.join('|')})\\s*[：:]`, 'g'))
  ]
  if (!matches.length) return normalizePortraitSections([{ label: '概述', text: normalized }])
  const rows = matches.map((match, index) => ({
    label: match[1],
    text: normalized.slice(
      match.index + match[0].length,
      matches[index + 1]?.index ?? normalized.length
    )
  }))
  const lead = normalized
    .slice(0, matches[0].index)
    .replace(/^[-*•]\s*/, '')
    .trim()
  return normalizePortraitSections(lead ? [{ label: '概述', text: lead }, ...rows] : rows)
}
export const portraitSectionHint = (label) =>
  SECTION_HINTS[portraitSectionLabel(label)] || '继续深挖本栏'

/** Normalize an injected card portrait into ordered, de-duplicated columns. */
export function normalizePortraitSections(value, { clip = 1200 } = {}) {
  const rows = Array.isArray(value) ? value : []
  const merged = new Map()
  for (const row of rows) {
    const label = portraitSectionLabel(row?.label)
    const body = text(row?.text).replace(/\s+/g, ' ')
    if (!label || !body || merged.has(label)) continue
    merged.set(label, body.slice(0, clip))
  }
  const ordered = PORTRAIT_SECTION_ORDER.filter((label) => merged.has(label))
  const extra = [...merged.keys()].filter((label) => !PORTRAIT_SECTION_ORDER.includes(label))
  return [...ordered, ...extra].map((label) => ({
    label,
    text: merged.get(label)
  }))
}

/**
 * Compact digest of the bound card, safe to embed in a seed or turn prompt.
 * `budget` is the total character allowance; the server rejects a focus longer
 * than 1600, so the per-column clip is derived from what is actually left.
 */
export function portraitSectionDigest(sections, { budget = 1300 } = {}) {
  const rows = normalizePortraitSections(sections)
  if (!rows.length) return ''
  const clip = Math.max(80, Math.floor(budget / rows.length) - 12)
  return rows.map((item) => `【${item.label}】${item.text.slice(0, clip)}`).join('\n')
}

/** One turn that deepens a single column without diverging off the card. */
export function portraitSectionPrompt(label, equipment = '', body = '') {
  const section = portraitSectionLabel(label)
  if (!section) return ''
  if (isTechnologyCabinSection(section)) {
    return technologyCabinPrompt(equipment, body)
  }
  const ask = SECTION_ASKS[section] || `围绕「${section}」继续深挖，给出更具体、可核验的结论。`
  const target = text(equipment) ? `「${text(equipment)}」` : '当前装备'
  const current = text(body) ? `\n本栏现有内容：${text(body).slice(0, 600)}` : ''
  return `仅针对${target}的「${section}」一栏继续深挖，保持装备身份不变，不要改成其他装备方向。${ask}${current}\n以技术攻关、作战流程推演和制胜逻辑深化为主，形成具体解决路径与本栏修订建议；证据缺口、失效边界和验证动作只在确实影响方案成立或研发决策时补充，不要求机械凑齐。`
}

/**
 * Seed instruction for a session opened from a capability card.  It states the
 * card's current five columns up front so the first turn already argues from
 * them, and it leaves both directions open: deepen a column, or diverge.
 */
export function capabilitySeedFocus(equipment, sections, { limit = 1560 } = {}) {
  const target = text(equipment) || '当前装备'
  const header = `以已有能力画像卡「${target}」为研究主体，保持装备身份和核心任务定位不变，深化当前画像及其作用机理。`
  const rules = [
    '优先识别研发该武器的关键技术卡点、工程痛点、指标耦合和系统集成难题，并给出多条可比较的解决路径。',
    '允许在本装备内部深度发散构型、材料、算法、接口、部署和保障方案，但不得自动改写成其他装备。',
    '同步推演作战流程和制胜逻辑，说明关键技术如何转化为作战动作、体系能力与制胜优势。',
    '输出具体修订建议；证据、失效边界和验证动作按决策需要补充，不机械凑项。只有显式切换到新质发散模式才生成新装备候选。'
  ]
    .map((item, index) => `${index + 1}. ${item}`)
    .join('\n')
  const frame = `${header}\n\n当前五栏：\n{digest}\n\n研究要求：\n${rules}`
  const digest = portraitSectionDigest(sections, {
    budget: limit - frame.length + '{digest}'.length
  })
  if (!digest) return `${header}\n\n研究要求：\n${rules}`.slice(0, limit)
  return frame.replace('{digest}', digest).slice(0, limit)
}

/** Explicit opt-in prompt that may leave the bound equipment identity. */
export function newWeaponDivergencePrompt(equipment = '', section = '') {
  const target = text(equipment) ? `能力画像「${text(equipment)}」` : '当前研究对象'
  const baseline = text(section) ? `，重点从「${text(section)}」栏暴露的缺口出发` : ''
  return `切换为“发散新质武器”模式。以${target}作为启发和对照基线${baseline}，允许突破原装备身份、任务链与作用机理。请先从任务链反转、作用机理、装备构型、交战窗口、成本交换和对手反适应等维度提出彼此正交的候选，再给出证据缺口与最低成本反制；暂不成卡，等待我确认方向。`
}

/** Opening suggestions for a card-bound session, replacing the generic pool. */
export function capabilityWelcomeSuggestions(equipment, sections, count = 4) {
  const rows = normalizePortraitSections(sections)
  if (!rows.length) return []
  return rows.slice(0, count).map((item) => portraitSectionPrompt(item.label, equipment, item.text))
}
