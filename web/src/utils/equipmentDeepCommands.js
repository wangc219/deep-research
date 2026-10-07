import { filterSlashCommands, matchSlashCommand, slashCommandRunMeta } from './slashCommands.js'

export const EQUIPMENT_DEEP_SLASH_COMMANDS = Object.freeze([
  {
    id: 'diverge',
    command: '/diverge',
    label: '开放发散',
    detail: '显式切换为新质武器发散，允许突破当前装备身份',
    runMeta: { equipment_deep_mode: 'new_weapon_diverge' }
  },
  {
    id: 'challenge',
    command: '/challenge',
    label: '对抗检验',
    detail: '寻找反例、最低成本反制与失效边界'
  },
  {
    id: 'synthesize',
    command: '/synthesize',
    label: '综合归纳',
    detail: '比较已有方向，形成可继续研究的前沿'
  },
  {
    id: 'card',
    command: '/card',
    label: '形成能力卡',
    detail: '用已收敛方向写五栏，不再扩展新候选',
    runMeta: { equipment_create_artifact: true }
  },
  {
    id: 'memory',
    command: '/memory',
    label: '查看决策记忆',
    detail: '读取当前会话窗口、步骤与决策记忆',
    clientAction: 'state'
  },
  {
    id: 'help',
    command: '/help',
    label: '命令说明',
    detail: '列出定向深研可用命令'
  }
])

export function matchEquipmentDeepSlashCommand(draft, commands = EQUIPMENT_DEEP_SLASH_COMMANDS) {
  return matchSlashCommand(draft, commands)
}

export function filterEquipmentDeepSlashCommands(
  draft,
  commands = EQUIPMENT_DEEP_SLASH_COMMANDS
) {
  return filterSlashCommands(draft, commands)
}

export function equipmentDeepSlashRunMeta(
  draft,
  commands = EQUIPMENT_DEEP_SLASH_COMMANDS
) {
  return slashCommandRunMeta(draft, commands)
}
