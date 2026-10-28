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
    title: '项目概述与研发需求',
    question: '为什么要研发？',
    scope: '背景、任务需求、现有技术不足、目标能力'
  },
  {
    title: '总体技术方案',
    question: '装备总体怎么设计',
    scope: '总体构型、系统架构、功能组成、工作模式、模块划分'
  },
  {
    title: '核心技术体系',
    question: '主要依靠哪些技术',
    scope: '核心技术、支撑技术、基础技术、关键部件技术及相互关系'
  },
  {
    title: '关键技术攻关',
    question: '最难的问题是什么？如何解决？',
    scope: '技术难点、瓶颈成因、失效因素、待验证假设、突破方向'
  },
  {
    title: '技术实现方案',
    question: '具体如何实现？',
    scope: '技术原理、实现机制、模块接口、实现步骤、备选路线'
  },
  {
    title: '技术路线与研发计划',
    question: '研发工作如何推进？',
    scope: '阶段划分、任务依赖、阶段成果、风险与资源需求'
  },
  {
    title: '预期成果与应用价值',
    question: '最终能形成什么？',
    scope: '预期形成的能力、适用场景、技术成熟度、成果交付'
  }
]

const technologyImplementationPlanPrompt = () =>
  `${TECHNOLOGY_SOLUTION_TRIGGER}，交付面向装备研发的技术方案，而不是资料综述。报告题名固定为“武器装备研发技术方案报告”，副题为“面向研发人员 · 技术路线设计 · 关键问题攻关 · 工程实现”。先给出“报告主线”：需求牵引—明确任务背景、目标与能力缺口；总体设计—确定总体构型、功能组成与技术架构；核心技术与关键攻关—明确技术机理、实现路径、瓶颈与突破方向。随后先列出“章节—核心内容—主要回答的问题”导航表，再依次使用七个精确章名：${TECHNOLOGY_SOLUTION_CHAPTERS.map((item, index) => `${index + 1}. ${item.title}（${item.scope}；${item.question}）`).join('；')}。若证据表明后半段关键机理、构型或工程可行性存疑，先回溯到失效的技术假设和分系统，必要时重构新质武器装备的主装备形态、作用原理与总体架构，不对原报告做局部润色。方案闭合原理样机、分级试验、可量测判据、阶段决策门和备选路线；区分已核验证据、工程推断与待试验假设，不编造精确参数。`

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
    label: '重构技术方案',
    hint: '存疑时回溯重构，形成可拆任务、做样机和测指标的研发方案',
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
  return `${purpose}。为「${target}」形成正式 S6 五栏能力卡：正文只能依次使用“概述、装备与技术实现、关键作战流程、形成能力与作战效果、制胜逻辑机理”五个精确栏名，不加“修订”等后缀，不增加第六栏。S5只负责入选；成卡前先为本卡生成一次创新、新颖且因果闭合的“解决思路”和“核心创新”，冻结为共享创新锚点，概述和技术实现必须共同引用且不得各自换题。概述严格按“当前背景、解决思路、达到效果、核心创新”四项分条简述，不写技术实现；技术栏与概述并列，显式承接同一解决思路和核心创新，围绕原理假设、依据、关键约束、候选路径、验证判据和可行性结论研究，后阶段配套问题仅在直接决定核心创新成立时纳入。流程栏闭合主体、条件、动作、状态、异常和转段；效果栏区分新增任务、直接战果、体系收益、敌方代价与判据；制胜栏闭合旧规则、作用链、交换关系、对手经济反制及新增代价。先分别起草五栏，再逐栏检查职责、完整因果、长度和跨栏重复，发现短栏或缺口必须先补写。每栏以 360–400 个有效中文字为常规目标，复杂因果可略多，禁止硬切、机械凑字、重复栏和跨栏复用。五栏全部通过自检后，调用 save_equipment_capability_draft 新增待核验版本，并在 structured_fields 中同时提交 capability_portrait_modules 与 capability_card_draft，两者均使用 ${S6_PORTRAIT_MODULE_KEYS.join('、')} 五个键；不得覆盖正式卡。`
}

const SECTION_ALIASES = new Map([
  ['制胜逻辑机理与对抗边界', '制胜逻辑机理'],
  ['制胜逻辑', '制胜逻辑机理'],
  ['能力画像概述', '概述']
])

const SECTION_ASKS = {
  概述: '目标是澄清装备定位、核心问题与关键变化。',
  装备与技术实现: '目标是理解技术如何实现、关键难点和可行路径。',
  关键作战流程: '目标是理解任务如何执行，以及关键环节如何衔接。',
  形成能力与作战效果: '目标是解释能力如何形成、能带来什么效果及其依据。',
  制胜逻辑机理: '目标是解释优势为何成立，以及在哪些条件下会改变。'
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
  mission: '研究该装备的技术实现，识别值得深入的问题，自主选择分析路径，给出有依据的判断。',
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
export function technologyCabinPrompt(
  equipment = '',
  body = '',
  action = 'mission',
  overview = ''
) {
  const target = text(equipment) ? `「${text(equipment)}」` : '当前装备'
  const task = TECHNOLOGY_CABIN_TASKS[action] || TECHNOLOGY_CABIN_TASKS.mission
  const baseline = text(overview) ? `参考概述：${text(overview).slice(0, 760)}。` : ''
  const source = text(body) ? `现有技术描述：${text(body).slice(0, 600)}。` : ''
  return `围绕${target}的「装备与技术实现」开展研究。${task}${baseline}${source}需要新证据时实际联合检索 Open Web、已授权本地知识库和 AMiner：用公开网页核验标准、工程实现与供应链，用知识库复用已有装备材料，用 AMiner 挖掘科学原理、技术路线和论文证据。将有效发现闭合为“装备/分系统—作用原理—可实现技术—工程约束—验证判据”链路，不罗列脱离装备的泛技术名词。现有描述可核验与修正，某一通道不可用时明确证据缺口，不预设结论。`
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
export function portraitSectionPrompt(label, equipment = '', body = '', overview = '') {
  const section = portraitSectionLabel(label)
  if (!section) return ''
  if (isTechnologyCabinSection(section)) {
    return technologyCabinPrompt(equipment, body, 'mission', overview)
  }
  const ask = SECTION_ASKS[section] || `围绕「${section}」继续深挖，给出更具体、可核验的结论。`
  const target = text(equipment) ? `「${text(equipment)}」` : '当前装备'
  const current = text(body) ? `\n本栏现有内容：${text(body).slice(0, 600)}` : ''
  return `继续研究${target}的「${section}」。${ask}${current}\n根据本栏目标自主选择研究路径和回答形式，现有描述可核验与修正。`
}

/**
 * Seed instruction for a session opened from a capability card.  It states the
 * card's current five columns up front so the first turn already argues from
 * them, and it leaves both directions open: deepen a column, or diverge.
 */
export function capabilitySeedFocus(equipment, sections, { limit = 1560 } = {}) {
  const target = text(equipment) || '当前装备'
  const header = `围绕「${target}」的能力画像继续研究，结合用户当前问题自主判断值得深入的方向。`
  const digest = portraitSectionDigest(sections, { budget: Math.max(0, limit - header.length - 8) })
  return `${header}\n参考背景：\n${digest}`.slice(0, limit)
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
  const overview = rows.find((item) => item.label === '概述')?.text || ''
  return rows
    .slice(0, count)
    .map((item) => portraitSectionPrompt(item.label, equipment, item.text, overview))
}
