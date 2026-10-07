import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  formatLegacyDeepJson,
  normalizeLegacyDeepJob,
  normalizeLegacyDeepMessage,
  projectLegacyDeepSession
} from '../../src/utils/equipmentLegacyDeepSession.js'

test('旧版深研消息从 payload 恢复分支、引用、metadata 与消息顺序', () => {
  const projection = projectLegacyDeepSession({
    session_id: 'legacy-session',
    payload: { title: '旧版创新议事', status: 'active' },
    messages: [
      {
        message_id: 'assistant-1',
        role: 'assistant',
        content: '综合结论',
        created_at: '2026-09-25T02:02:00Z',
        payload: {
          sequence: 2,
          parent_message_id: 'user-1',
          branch_id: 'main',
          turn_id: 'turn-1',
          message_kind: 'message',
          status: 'completed',
          artifact_refs_json: '["artifact-1"]',
          version_refs: [{ version_id: 'version-2' }],
          metadata_json: '{"stage":"s4_mapping","confidence":0.78}'
        }
      },
      {
        message_id: 'user-1',
        role: 'user',
        content: '继续分析反制边界',
        created_at: '2026-09-25T02:01:00Z',
        payload: { sequence: 1, branch_id: 'main', status: 'completed', metadata: {} }
      }
    ]
  })

  assert.equal(projection.title, '旧版创新议事')
  assert.equal(projection.archived, false)
  assert.deepEqual(
    projection.messages.map((item) => item.id),
    ['user-1', 'assistant-1']
  )
  assert.deepEqual(projection.messages[1].artifactRefs, ['artifact-1'])
  assert.deepEqual(projection.messages[1].versionRefs, [{ version_id: 'version-2' }])
  assert.deepEqual(projection.messages[1].metadata, {
    stage: 's4_mapping',
    confidence: 0.78
  })
  assert.equal(projection.messages[1].parentMessageId, 'user-1')
  assert.equal(projection.messages[1].turnId, 'turn-1')
})

test('首版导入直接写入 payload 的消息 metadata 不会丢失', () => {
  const message = normalizeLegacyDeepMessage({
    message_id: 'direct-import',
    role: 'assistant',
    content: '旧内容',
    payload: { model_profile_id: 'profile-a', deliberation: { verdict: 'revise' } }
  })

  assert.deepEqual(message.metadata, {
    model_profile_id: 'profile-a',
    deliberation: { verdict: 'revise' }
  })
})

test('旧版任务恢复 checkpoint、错误、阶段与关联标识', () => {
  const job = normalizeLegacyDeepJob({
    job_id: 'job-1',
    status: 'failed',
    error: '',
    payload: {
      stage: 'council_critique',
      kind: 'deep_divergence_v1',
      branch_id: 'branch-red',
      state_version: 7,
      child_run_id: 'run-child',
      root_message_id: 'message-root',
      checkpoint_json: '{"phase":"critique","completed_agents":["red-team"]}',
      error: '核验任务失败'
    }
  })

  assert.equal(job.statusLabel, '失败')
  assert.equal(job.statusTone, 'danger')
  assert.equal(job.stage, 'council_critique')
  assert.equal(job.branchId, 'branch-red')
  assert.equal(job.stateVersion, 7)
  assert.equal(job.childRunId, 'run-child')
  assert.equal(job.rootMessageId, 'message-root')
  assert.equal(job.error, '核验任务失败')
  assert.deepEqual(job.checkpoint, {
    phase: 'critique',
    completed_agents: ['red-team']
  })
})

test('旧版会话投影完整保留分支并把归档会话标为只读', () => {
  const projection = projectLegacyDeepSession({
    session_id: 'archived-session',
    status: 'archived',
    jobs: [
      { job_id: 'older', status: 'completed', updated_at: '2026-09-24T00:00:00Z' },
      { job_id: 'newer', status: 'running', updated_at: '2026-09-25T00:00:00Z' }
    ],
    branches: [
      {
        branch_id: 'branch-b',
        payload: {
          title: '反制分支',
          parent_branch_id: 'main',
          forked_from_message_id: 'message-2',
          child_session_id: 'session-child',
          status: 'active'
        },
        created_at: '2026-09-25T02:00:00Z'
      },
      { branch_id: 'main', title: '主线', created_at: '2026-09-25T01:00:00Z' }
    ]
  })

  assert.equal(projection.archived, true)
  assert.deepEqual(
    projection.jobs.map((item) => item.id),
    ['newer', 'older']
  )
  assert.deepEqual(
    projection.branches.map((item) => item.id),
    ['main', 'branch-b']
  )
  assert.equal(projection.branches[1].parentBranchId, 'main')
  assert.equal(projection.branches[1].forkedFromMessageId, 'message-2')
  assert.equal(projection.branches[1].childSessionId, 'session-child')
})

test('畸形旧 JSON 安全降级且组件只通过 submit 事件交给父页', () => {
  const message = normalizeLegacyDeepMessage({
    payload: {
      artifact_refs_json: 'legacy-artifact-path',
      metadata_json: '{broken'
    }
  })
  assert.deepEqual(message.artifactRefs, ['legacy-artifact-path'])
  assert.equal(message.metadata, '{broken')
  assert.equal(formatLegacyDeepJson('{"ok":true}'), '{\n  "ok": true\n}')

  const scalarCheckpoint = normalizeLegacyDeepJob({ payload: { checkpoint_json: 'stage-done' } })
  assert.equal(scalarCheckpoint.checkpoint, 'stage-done')

  const component = readFileSync(
    new URL('../../src/components/equipment/EquipmentLegacyDeepSession.vue', import.meta.url),
    'utf8'
  )
  assert.match(component, /defineEmits\(\['submit'\]\)/)
  assert.match(component, /emit\('submit', content\)/)
  assert.doesNotMatch(component, /\bfetch\s*\(|apiGet|apiPost|equipmentApi/)
  assert.match(component, /projection\.archived/)
  assert.match(component, /Checkpoint/)
  assert.match(component, /消息 metadata/)
})
