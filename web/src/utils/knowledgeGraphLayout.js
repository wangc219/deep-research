export const KNOWLEDGE_GRAPH_LAYOUTS = Object.freeze({
  FORCE: 'force',
  GROUPED: 'grouped'
})

export const OTHER_NODE_TYPE = '其他'

function normalizeType(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || '').trim()).find(Boolean) || ''
  }
  return String(value || '').trim()
}

export function getKnowledgeGraphNodeType(node) {
  return (
    normalizeType(node?.type) ||
    normalizeType(node?.normalized?.type) ||
    normalizeType(node?.properties?.label) ||
    normalizeType(node?.labels) ||
    OTHER_NODE_TYPE
  )
}

function compareText(left, right) {
  return String(left).localeCompare(String(right), 'zh-CN', {
    numeric: true,
    sensitivity: 'base'
  })
}

function compareNodes(left, right) {
  const leftName = left?.name ?? left?.label ?? left?.id ?? ''
  const rightName = right?.name ?? right?.label ?? right?.id ?? ''
  return compareText(leftName, rightName) || compareText(left?.id ?? '', right?.id ?? '')
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max)
}

/**
 * Build deterministic grid cells for an entity-type grouped graph layout.
 * Groups share equally sized slots, with an empty grid track between slots so
 * colors/types remain visually distinct after G6 fits the graph to the canvas.
 */
export function buildKnowledgeGraphGroupLayout(nodes = [], viewport = {}) {
  const buckets = new Map()
  for (const node of nodes || []) {
    const type = getKnowledgeGraphNodeType(node)
    if (!buckets.has(type)) buckets.set(type, [])
    buckets.get(type).push(node)
  }

  const groups = Array.from(buckets, ([type, items]) => ({
    type,
    nodes: [...items].sort(compareNodes)
  })).sort(
    (left, right) => right.nodes.length - left.nodes.length || compareText(left.type, right.type)
  )

  if (groups.length === 0) {
    return { positions: {}, groups: [], rows: 1, cols: 1 }
  }

  const width = Math.max(Number(viewport.width) || 1, 1)
  const height = Math.max(Number(viewport.height) || 1, 1)
  const aspectRatio = clamp(width / height, 0.75, 2.5)
  const groupCols = clamp(Math.round(Math.sqrt(groups.length * aspectRatio)), 1, groups.length)
  const groupRows = Math.ceil(groups.length / groupCols)

  const groupPlans = groups.map((group) => {
    const innerCols = Math.max(1, Math.ceil(Math.sqrt(group.nodes.length * aspectRatio)))
    return {
      ...group,
      innerCols,
      innerRows: Math.ceil(group.nodes.length / innerCols)
    }
  })

  const slotCols = Math.max(...groupPlans.map((group) => group.innerCols))
  const slotRows = Math.max(...groupPlans.map((group) => group.innerRows))
  const groupGap = 1
  const cols = groupCols * slotCols + (groupCols - 1) * groupGap
  const rows = groupRows * slotRows + (groupRows - 1) * groupGap
  const positions = {}

  groupPlans.forEach((group, groupIndex) => {
    const blockRow = Math.floor(groupIndex / groupCols)
    const blockCol = groupIndex % groupCols
    const rowOffset =
      blockRow * (slotRows + groupGap) + Math.floor((slotRows - group.innerRows) / 2)
    const colOffset =
      blockCol * (slotCols + groupGap) + Math.floor((slotCols - group.innerCols) / 2)

    group.nodes.forEach((node, nodeIndex) => {
      positions[String(node.id)] = {
        row: rowOffset + Math.floor(nodeIndex / group.innerCols),
        col: colOffset + (nodeIndex % group.innerCols)
      }
    })
  })

  return {
    positions,
    rows,
    cols,
    groups: groupPlans.map((group) => ({ type: group.type, count: group.nodes.length }))
  }
}
