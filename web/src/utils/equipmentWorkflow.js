export const EQUIPMENT_WORKFLOW_STEPS = [
  {
    id: 'queries',
    path: '/equipment/queries',
    label: 'Query 发现',
    shortLabel: '发现需求',
    description: '生成、审核研究方向',
    action: '选择 Query 启动研究'
  },
  {
    id: 'runs',
    path: '/equipment/runs',
    label: '研究任务',
    shortLabel: '启动研究',
    description: '运行 Agent 并沉淀证据',
    action: '进入研究任务'
  },
  {
    id: 'capabilities',
    path: '/equipment/capabilities',
    label: '能力画像',
    shortLabel: '审阅画像',
    description: '查看正式 S6 五栏成果',
    action: '查看能力画像',
    acceptsRun: true
  },
  {
    id: 'deep-thinking',
    path: '/equipment/deep-thinking',
    label: '深研对话',
    shortLabel: '定向深研',
    description: '围绕装备或单栏继续研究',
    action: '发起定向深研',
    acceptsRun: true
  },
  {
    id: 'reports',
    path: '/equipment/reports',
    label: '研究报告',
    shortLabel: '获取报告',
    description: '阅读、导出最终成果',
    action: '查看研究报告',
    acceptsRun: true
  },
  {
    id: 'favorites',
    path: '/equipment/favorites',
    label: '成果收藏',
    shortLabel: '收藏复用',
    description: '沉淀可复用的能力画像',
    action: '查看收藏成果'
  }
]

export const resolveEquipmentWorkflowStep = (path = '') => {
  const normalized = String(path || '')
  return EQUIPMENT_WORKFLOW_STEPS.find((step) =>
    normalized === step.path || normalized.startsWith(`${step.path}/`)
  ) || EQUIPMENT_WORKFLOW_STEPS[0]
}

export const resolveEquipmentWorkflowRunId = (route = {}) =>
  String(route?.query?.run || route?.params?.runId || '').trim()

export const equipmentWorkflowLocation = (step, runId = '') => {
  const target = typeof step === 'string'
    ? EQUIPMENT_WORKFLOW_STEPS.find((item) => item.id === step)
    : step
  if (!target) return { path: '/equipment/queries' }
  const normalizedRunId = String(runId || '').trim()
  return {
    path: target.path,
    ...(target.acceptsRun && normalizedRunId ? { query: { run: normalizedRunId } } : {})
  }
}

export const nextEquipmentWorkflowStep = (currentId = '') => {
  const index = EQUIPMENT_WORKFLOW_STEPS.findIndex((step) => step.id === currentId)
  return EQUIPMENT_WORKFLOW_STEPS[index >= 0 && index < EQUIPMENT_WORKFLOW_STEPS.length - 1 ? index + 1 : 0]
}
