export const editableWorkspacePath = (file) => {
  if (!file || file.readonly) return ''
  const path = String(file.path || '')
  const runtimeRoot = '/home/gem/user-data'
  let workspacePath = ''
  if (file.workspace) workspacePath = path
  else if (path.startsWith(`${runtimeRoot}/`)) workspacePath = path.slice(runtimeRoot.length)
  else if (file.workdir) {
    const match = String(file.artifact_url || '').match(
      /^\/api\/chat\/thread\/[^/]+\/artifacts\/home\/gem\/user-data(\/.*)$/
    )
    workspacePath = match?.[1] || ''
  }
  if (!workspacePath.startsWith('/') || workspacePath.split('/').includes('..')) return ''
  return workspacePath
}
