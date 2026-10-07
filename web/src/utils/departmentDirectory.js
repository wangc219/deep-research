export const buildDepartmentDirectory = (departments = []) => {
  const nodesById = new Map(
    departments.map((department) => [
      department.id,
      {
        key: String(department.id),
        title: department.name,
        userCount: Number(department.user_count) || 0,
        department,
        children: []
      }
    ])
  )

  const roots = []
  for (const node of nodesById.values()) {
    const parent = nodesById.get(node.department.parent_id)
    if (parent && parent !== node) {
      parent.children.push(node)
    } else {
      roots.push(node)
    }
  }

  return roots
}

export const buildDepartmentPathMap = (departments = []) => {
  const departmentsById = new Map(departments.map((department) => [department.id, department]))
  const paths = new Map()

  for (const department of departments) {
    const names = []
    const visited = new Set()
    let current = department

    while (current && !visited.has(current.id)) {
      visited.add(current.id)
      names.unshift(current.name)
      current = departmentsById.get(current.parent_id)
    }

    paths.set(department.id, names.join(' / '))
  }

  return paths
}
