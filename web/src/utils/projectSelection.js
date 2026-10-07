export const AUTO_PROJECT_ID = '__auto__'

export const filterProjects = (projects, query = '') => {
  const keyword = String(query).trim().toLocaleLowerCase()
  if (!keyword) return projects
  return projects.filter((project) =>
    [project.name, project.uid, project.id].some((value) =>
      String(value || '').toLocaleLowerCase().includes(keyword)
    )
  )
}

export const projectDisplayName = (project, showOwner = false) => {
  const name = project?.name || project?.id || '未命名项目'
  return showOwner && project?.uid ? `${name} · ${project.uid}` : name
}

export const formatRelativeTime = (value, now = Date.now()) => {
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return ''

  const elapsed = Math.max(0, Number(now) - timestamp)
  const minute = 60 * 1000
  const hour = 60 * minute
  const day = 24 * hour
  if (elapsed < minute) return '刚刚'
  if (elapsed < hour) return `${Math.floor(elapsed / minute)}分钟前`
  if (elapsed < day) return `${Math.floor(elapsed / hour)}小时前`
  if (elapsed < 30 * day) return `${Math.floor(elapsed / day)}天前`
  if (elapsed < 365 * day) return `${Math.floor(elapsed / (30 * day))}个月前`
  return `${Math.floor(elapsed / (365 * day))}年前`
}
