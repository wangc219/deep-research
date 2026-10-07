import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  capabilityConfidence,
  capabilityDimensions,
  capabilityDirection,
  capabilityPortraitComplete,
  capabilityPortraitModules,
  capabilityTitle,
  normalizeCapability
} from '../../src/utils/equipmentCapabilities.js'

describe('旧版能力画像兼容', () => {
  it('把旧 capability_card_draft 映射为新版五栏结构', () => {
    const result = normalizeCapability({
      id: 'version-1',
      run_id: 'run-1',
      primary_equipment_identity: '百链系统',
      equipment_forms: ['巡飞节点', '中继节点'],
      capability_gap: '传统链路依赖单点',
      capability_card_draft: {
        operational_process: '发现、确认、接力、评估',
        technology_implementation: '模块化感知与局部自治',
        capability_effects: '缩短响应时间',
        winning_logic: '把时间变成作战资源'
      }
    })

    assert.equal(result.equipment_name, '百链系统')
    assert.equal(result.equipment_direction, '巡飞节点\n中继节点')
    assert.equal(result.problem_statement, '传统链路依赖单点')
    assert.equal(result.operational_process, '发现、确认、接力、评估')
    assert.equal(result.scientific_principle, '模块化感知与局部自治')
    assert.equal(result.capability_outcome, '缩短响应时间')
    assert.equal(result.winning_mechanism, '把时间变成作战资源')
  })

  it('新版顶层字段优先且保留未知字段', () => {
    const result = normalizeCapability({
      name: '新版装备',
      operational_process: ['步骤一', '步骤二'],
      scientific_principle: '新版原理',
      capability_card_draft: { scientific_principle: '旧版原理' },
      extension_field: { kept: true }
    })

    assert.equal(result.operational_process, '步骤一\n步骤二')
    assert.equal(result.scientific_principle, '新版原理')
    assert.deepEqual(result.extension_field, { kept: true })
  })

  it('从旧画像正文的中文引号中恢复具体装备名称', () => {
    const result = normalizeCapability({
      name: '蜂群突防型',
      deep_capability_portrait: '概述：“苍隼无人机”可协同执行侦察任务。'
    })

    assert.equal(result.equipment_name, '')
    assert.equal(capabilityTitle(result), '苍隼无人机')
  })

  it('把旧版 XX型 方向显示为 XX型装备', () => {
    const result = normalizeCapability({ name: '蜂群突防型' })

    assert.equal(capabilityDirection(result), '蜂群突防型装备')
  })

  it('保留像装备名称的主维度，只过滤辅助维度中的装备名称', () => {
    const result = capabilityDimensions({
      capability_classification: {
        primary_dimension: '某型导弹',
        secondary_dimensions: ['另一型导弹', '侦察维度', '某型导弹'],
        classification_basis: '根据任务用途分类'
      }
    })

    assert.deepEqual(result.values, ['某型导弹', '侦察感知维度'])
    assert.equal(result.basis, '根据任务用途分类')
  })

  it('旧画像的“制胜逻辑”栏名规范化为正式 S6 栏名且满足五栏完整性', () => {
    const portrait = {
      deep_capability_portrait: [
        '概述：面向近距防御。',
        '装备与技术实现：采用分布式感知。',
        '关键作战流程：发现、跟踪、拦截。',
        '形成能力与作战效果：压缩响应时间。',
        '制胜逻辑：以协同速度取得优势。'
      ].join('\n')
    }

    const modules = capabilityPortraitModules(portrait)
    assert.equal(modules.at(-1)?.label, '制胜逻辑机理')
    assert.equal(modules.at(-1)?.text, '以协同速度取得优势。')
    assert.equal(capabilityPortraitComplete(portrait), true)
  })

  it('去掉旧画像概述中的重复能力分类和各模块末尾分隔符', () => {
    const portrait = {
      deep_capability_portrait: [
        '概述：能力分类：主：突防维度；辅：侦察感知维度。未来战场需要缩短判断链。 -',
        '装备与技术实现：采用分布式感知与局部自治。 -',
        '关键作战流程：发现、确认、接力、评估。 -',
        '形成能力与作战效果：压缩响应时间。 -',
        '制胜逻辑机理：以协同速度取得优势。'
      ].join('\n')
    }

    const modules = capabilityPortraitModules(portrait)
    assert.equal(modules[0]?.text, '未来战场需要缩短判断链。')
    assert.equal(modules[1]?.text, '采用分布式感知与局部自治。')
    assert.equal(modules[2]?.text, '发现、确认、接力、评估。')
    assert.equal(modules[3]?.text, '压缩响应时间。')
  })

  it('识别带修订后缀的旧深研卡并按正式 S6 顺序呈现五栏', () => {
    const portrait = {
      capability_image: [
        '概述：场景与定位。',
        '装备与技术实现（修订）：总体构型与主备路线。',
        '制胜逻辑机理（修订）：交换关系与反制代价。',
        '关键作战流程：条件动作与状态转段。',
        '形成能力与作战效果：直接战果与体系收益。'
      ].join('\n')
    }

    const modules = capabilityPortraitModules(portrait)
    assert.deepEqual(
      modules.map((item) => item.label),
      ['概述', '装备与技术实现', '关键作战流程', '形成能力与作战效果', '制胜逻辑机理']
    )
    assert.equal(modules[1].text, '总体构型与主备路线。')
    assert.equal(capabilityPortraitComplete(portrait), true)
  })

  it('置信度显示保留一位小数', () => {
    assert.equal(capabilityConfidence({ confidence: 0.645 }), '64.5%')
    assert.equal(capabilityConfidence({ confidence: 64 }), '64.0%')
  })
})
