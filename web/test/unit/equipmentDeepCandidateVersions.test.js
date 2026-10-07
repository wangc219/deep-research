import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  buildSessionCandidateVersionCards,
  candidateBaselineDiff,
  candidatePortraitSlots,
  candidateVersionSessionId,
  candidateVersionStatus,
  candidateVersionStatusLabel,
  findCandidateFormalBaseline,
  normalizeCandidateVersion,
  sessionCandidateVersions
} from '../../src/utils/equipmentDeepCandidateVersions.js'

const portrait = (suffix) => ({
  overview: `概述${suffix}`,
  technology_implementation: `技术${suffix}`,
  operational_process: `流程${suffix}`,
  capability_effects: `效果${suffix}`,
  winning_logic: `制胜${suffix}`
})

const versions = [
  {
    version_id: 'baseline-h1',
    created_at: '2026-09-20T02:00:00Z',
    snapshot: {
      status: 'formal',
      version_no: 1,
      name: '裂棱眩扰弹',
      hypothesis_id: 'hypothesis-1',
      capability_portrait_modules: portrait('（正式）')
    }
  },
  {
    version_id: 'candidate-v2',
    created_at: '2026-09-25T02:00:00Z',
    snapshot: {
      status: 'pending_verification',
      version_no: 2,
      session_id: 'session-a',
      name: '裂棱眩扰弹 · 夜战型',
      hypothesis_id: 'hypothesis-1',
      evidence_refs: ['evidence-1'],
      structured_fields: {
        capability_portrait_modules: portrait('（深研）')
      }
    }
  },
  {
    version_id: 'candidate-v3',
    created_at: '2026-09-25T03:00:00Z',
    snapshot: {
      status: 'deleted',
      version_no: 3,
      source_session_id: 'session-a',
      name: '裂棱眩扰弹 · 低成本型',
      hypothesis_id: 'hypothesis-1',
      capability_portrait_modules: portrait('（隐藏）')
    }
  },
  {
    version_id: 'other-session-v4',
    created_at: '2026-09-25T04:00:00Z',
    snapshot: {
      status: 'verified',
      version_no: 4,
      session_id: 'session-b',
      name: '其他会话候选',
      hypothesis_id: 'hypothesis-1',
      capability_portrait_modules: portrait('（其他）')
    }
  }
]

test('候选版本严格按 session_id 过滤且保留已隐藏版本供恢复', () => {
  const rows = sessionCandidateVersions(versions, 'session-a')

  assert.deepEqual(
    rows.map((item) => item.version_id),
    ['candidate-v3', 'candidate-v2']
  )
  assert.deepEqual(
    rows.map((item) => item.status),
    ['deleted', 'pending_verification']
  )
  assert.equal(candidateVersionSessionId(versions[1]), 'session-a')
  assert.equal(candidateVersionSessionId(versions[2]), 'session-a')
  assert.deepEqual(sessionCandidateVersions(versions, ''), [])
})

test('原生 structured_fields 与旧版 snapshot 都能投影为五栏预览', () => {
  const normalized = normalizeCandidateVersion(versions[1])
  const slots = candidatePortraitSlots(normalized)

  assert.equal(normalized.version_id, 'candidate-v2')
  assert.equal(normalized.version_no, 2)
  assert.equal(normalized.evidence_refs[0], 'evidence-1')
  assert.equal(slots.length, 5)
  assert.equal(slots.every((item) => item.complete), true)
  assert.equal(slots[0].text, '概述（深研）')
  assert.equal(slots[4].text, '制胜（深研）')
})

test('候选按谱系匹配不可变正式基线并只输出有变化的字段', () => {
  const candidate = normalizeCandidateVersion(versions[1])
  const baseline = findCandidateFormalBaseline(candidate, versions)
  const diff = candidateBaselineDiff(candidate, baseline)

  assert.equal(baseline.version_id, 'baseline-h1')
  assert.ok(diff.some((item) => item.label === '装备名称'))
  assert.ok(diff.some((item) => item.label === '概述'))
  assert.ok(diff.every((item) => item.before !== item.after))

  const cards = buildSessionCandidateVersionCards(versions, 'session-a')
  assert.equal(cards.length, 2)
  assert.equal(cards[1].completedModules, 5)
  assert.equal(cards[1].baseline.version_id, 'baseline-h1')
  assert.ok(cards[1].diff.length >= 6)
})

test('版本状态兼容 React/旧数据别名并提供一致中文标签', () => {
  assert.equal(candidateVersionStatus({ status: 'approved' }), 'verified')
  assert.equal(candidateVersionStatus({ status: 'rollback' }), 'rolled_back')
  assert.equal(candidateVersionStatus({ status: 'unverified' }), 'pending_verification')
  assert.equal(candidateVersionStatus({ version_id: 'legacy-draft' }), 'pending_verification')
  assert.equal(candidateVersionStatus({ version_id: 'baseline-old' }), 'formal')
  assert.equal(candidateVersionStatusLabel('deleted'), '已隐藏')
  assert.equal(candidateVersionStatusLabel('verified'), '已核验')
})

test('独立 Vue 组件覆盖加载、核验、隐藏、恢复、永久删除和正式基线差异', () => {
  const source = readFileSync(
    new URL(
      '../../src/components/equipment/EquipmentDeepCandidateVersions.vue',
      import.meta.url
    ),
    'utf8'
  )

  assert.match(source, /buildSessionCandidateVersionCards/)
  assert.match(source, /equipmentApi\.listCapabilityVersions/)
  assert.match(source, /equipmentApi\.verifyCapabilityVersion/)
  assert.match(source, /equipmentApi\.deleteCapabilityVersion/)
  assert.match(source, /equipmentApi\.restoreCapabilityVersion/)
  assert.match(source, /equipmentApi\.purgeCapabilityVersion/)
  assert.match(source, /本会话候选能力卡/)
  assert.match(source, /五栏能力画像/)
  assert.match(source, /与正式基线差异/)
  assert.match(source, /隐藏版本/)
  assert.match(source, /恢复版本/)
  assert.match(source, /defineEmits\(\['loaded', 'changed', 'error', 'open-portrait'\]\)/)
  assert.doesNotMatch(source, /EquipmentDeepThinkingView|AgentChatComponent/)
})
