export const S5_SCORE_SCHEMA = 's5_five_dimension_v1'

export const S5_SCORE_DIMENSIONS = [
  {
    key: 'innovation',
    label: '创新性',
    weight: 30,
    principle: '判断是否形成新的作用机理、装备构型或制胜关系，而非对常规方案换名或小幅升级；其中机理/装备创新占创新性评分的 75%，命名新质度占 15%，名称与本体一致性占 10%。'
  },
  {
    key: 'demand',
    label: '需求性',
    weight: 30,
    principle: '判断是否直接回应当前 Query 的作战对象、关键阶段和任务断点，补齐后能否改变实际作战后果，避免泛化需求或脱离任务场景。'
  },
  {
    key: 'feasibility',
    label: '科学可行性',
    weight: 20,
    principle: '判断物理原理、作用链和系统集成关系是否自洽，关键假设是否可验证；该项不等同于已具备成熟度，也不以公开证据不足直接否定前瞻方案。'
  },
  {
    key: 'effectiveness',
    label: '效能性',
    weight: 10,
    principle: '判断装备动作能否闭合到明确直接战果，并实际改变发现、火力、突防、拦截、毁伤、压制、拒止或威慑等任务效果。'
  },
  {
    key: 'development',
    label: '发展性',
    weight: 10,
    principle: '判断方案面对对手反适应和场景演化时是否仍有持续增量，是否具备清晰的迭代空间、体系扩展价值和可形成后续装备谱系的潜力。'
  }
]

const normalizedScore = (value) => {
  if (value === '' || value === null || value === undefined) return null
  const number = Number(value)
  if (!Number.isFinite(number)) return null
  const normalized = number > 1 ? number / 100 : number
  return normalized >= 0 && normalized <= 1 ? normalized : null
}

export const capabilityS5Scorecard = (item = {}) => {
  const raw = item.s5_dimension_scores && typeof item.s5_dimension_scores === 'object'
    ? item.s5_dimension_scores
    : {}
  const scores = Object.fromEntries(
    S5_SCORE_DIMENSIONS.map(({ key }) => [key, normalizedScore(raw[key])])
  )
  const complete = S5_SCORE_DIMENSIONS.every(({ key }) => scores[key] !== null)
  const weightedScore = complete
    ? S5_SCORE_DIMENSIONS.reduce(
        (sum, { key, weight }) => sum + scores[key] * weight / 100,
        0
      )
    : null
  return {
    complete,
    scores,
    weightedScore,
    schema: String(item.s5_score_schema || (complete ? S5_SCORE_SCHEMA : ''))
  }
}

export const emptyS5ScoreInput = () => Object.fromEntries(
  S5_SCORE_DIMENSIONS.map(({ key }) => [key, ''])
)
