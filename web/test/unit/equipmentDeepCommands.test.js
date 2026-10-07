import assert from 'node:assert/strict'
import test from 'node:test'
import {
  EQUIPMENT_DEEP_SLASH_COMMANDS,
  equipmentDeepSlashRunMeta,
  filterEquipmentDeepSlashCommands,
  matchEquipmentDeepSlashCommand
} from '../../src/utils/equipmentDeepCommands.js'

test('深研 slash 命令与 React 基线保持六项语义', () => {
  assert.deepEqual(
    EQUIPMENT_DEEP_SLASH_COMMANDS.map((item) => item.command),
    ['/diverge', '/challenge', '/synthesize', '/card', '/memory', '/help']
  )
})

test('slash 面板按命令、ID 和中文标题过滤', () => {
  assert.deepEqual(
    filterEquipmentDeepSlashCommands('/ch').map((item) => item.id),
    ['challenge']
  )
  assert.deepEqual(
    filterEquipmentDeepSlashCommands('/综合').map((item) => item.id),
    ['synthesize']
  )
  assert.equal(filterEquipmentDeepSlashCommands(' /card 立即执行').length, 0)
})

test('输入完整命令可匹配参数并附加成卡运行元数据', () => {
  assert.equal(matchEquipmentDeepSlashCommand('/CARD 使用当前方向')?.id, 'card')
  assert.deepEqual(equipmentDeepSlashRunMeta('/card 使用当前方向'), {
    equipment_create_artifact: true
  })
  assert.deepEqual(equipmentDeepSlashRunMeta('/diverge 从技术缺口发散'), {
    equipment_deep_mode: 'new_weapon_diverge'
  })
  assert.deepEqual(equipmentDeepSlashRunMeta('/memory'), {})
  assert.equal(matchEquipmentDeepSlashCommand('普通问题'), null)
})
