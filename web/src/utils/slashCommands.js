const normalizedDraft = (value) => String(value ?? '').trimStart()

export function matchSlashCommand(draft, commands = []) {
  const value = normalizedDraft(draft)
  if (!value.startsWith('/')) return null
  const name = value.slice(1).split(/\s+/, 1)[0].toLowerCase()
  return commands.find((item) => String(item?.id || '').toLowerCase() === name) || null
}

export function filterSlashCommands(draft, commands = []) {
  const value = normalizedDraft(draft)
  if (!value.startsWith('/') || /\s/.test(value)) return []
  const query = value.slice(1).toLowerCase()
  return commands.filter((item) => {
    const command = String(item?.command || '').replace(/^\//, '').toLowerCase()
    const id = String(item?.id || '').toLowerCase()
    const label = String(item?.label || '').toLowerCase()
    return command.startsWith(query) || id.startsWith(query) || label.includes(query)
  })
}

export function slashCommandRunMeta(draft, commands = []) {
  const command = matchSlashCommand(draft, commands)
  return command?.runMeta && typeof command.runMeta === 'object' ? command.runMeta : {}
}
