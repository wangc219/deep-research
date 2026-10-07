const EQUIPMENT_ROUTE_PREFIX = '/equipment/'
const EQUIPMENT_DEEP_THINKING_PREFIX = '/equipment/deep-thinking'
const EQUIPMENT_FAVORITES_PATH = '/equipment/favorites'
const EQUIPMENT_QUERIES_PATH = '/equipment/queries'
const EQUIPMENT_RUNS_PATH = '/equipment/runs'
const EQUIPMENT_CAPABILITIES_PATH = '/equipment/capabilities'
const EQUIPMENT_REPORTS_PATH = '/equipment/reports'
const AGENT_ROUTE_PREFIX = '/agent'

export const routeViewKey = (target) => {
  const path = String(target?.path || '')
  if (
    path === EQUIPMENT_DEEP_THINKING_PREFIX ||
    path.startsWith(`${EQUIPMENT_DEEP_THINKING_PREFIX}/`)
  ) {
    return 'equipment-deep-thinking'
  }
  if (path === EQUIPMENT_FAVORITES_PATH) return 'equipment-favorites'
  if (path === EQUIPMENT_QUERIES_PATH) return 'equipment-queries'
  if (path === EQUIPMENT_RUNS_PATH) return 'equipment-runs'
  if (path.startsWith(`${EQUIPMENT_RUNS_PATH}/`)) return 'equipment-run-detail'
  if (path === EQUIPMENT_CAPABILITIES_PATH) return 'equipment-capabilities'
  if (path === EQUIPMENT_REPORTS_PATH) return 'equipment-reports'
  if (path.startsWith(EQUIPMENT_ROUTE_PREFIX)) return 'equipment-workbench'
  if (path === AGENT_ROUTE_PREFIX || path.startsWith(`${AGENT_ROUTE_PREFIX}/`)) {
    return 'agent-workspace'
  }
  return path
}
