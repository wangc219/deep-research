import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  EQUIPMENT_WORKFLOW_STEPS,
  equipmentWorkflowLocation,
  nextEquipmentWorkflowStep,
  resolveEquipmentWorkflowRunId,
  resolveEquipmentWorkflowStep
} from '../../src/utils/equipmentWorkflow.js'

const workflowSource = readFileSync(
  new URL('../../src/components/equipment/EquipmentWorkflowNav.vue', import.meta.url),
  'utf8'
)
const layoutSource = readFileSync(new URL('../../src/layouts/AppLayout.vue', import.meta.url), 'utf8')

test('装备导航按从 Query 到成果复用的完整流程排列', () => {
  assert.deepEqual(
    EQUIPMENT_WORKFLOW_STEPS.map((step) => step.id),
    ['queries', 'runs', 'capabilities', 'deep-thinking', 'reports', 'favorites']
  )
  assert.equal(resolveEquipmentWorkflowStep('/equipment/runs/run-1').id, 'runs')
  assert.equal(resolveEquipmentWorkflowStep('/equipment/deep-thinking/session-1').id, 'deep-thinking')
  assert.equal(nextEquipmentWorkflowStep('capabilities').id, 'deep-thinking')
  assert.equal(nextEquipmentWorkflowStep('favorites').id, 'queries')
})

test('任务上下文只传递给支持按 run 定位的后续页面', () => {
  assert.equal(resolveEquipmentWorkflowRunId({ query: { run: 'run-1' }, params: {} }), 'run-1')
  assert.equal(resolveEquipmentWorkflowRunId({ query: {}, params: { runId: 'run-2' } }), 'run-2')
  assert.deepEqual(equipmentWorkflowLocation('capabilities', 'run-1'), {
    path: '/equipment/capabilities',
    query: { run: 'run-1' }
  })
  assert.deepEqual(equipmentWorkflowLocation('deep-thinking', 'run-1'), {
    path: '/equipment/deep-thinking',
    query: { run: 'run-1' }
  })
  assert.deepEqual(equipmentWorkflowLocation('runs', 'run-1'), { path: '/equipment/runs' })
})

test('装备页面常驻全流程导航，并在窄屏保持横向即时访问', () => {
  assert.match(layoutSource, /<EquipmentWorkflowNav v-if="isEquipmentRoute"/)
  assert.match(layoutSource, /class="app-route-stage"/)
  assert.match(workflowSource, /aria-label="装备研究全流程导航"/)
  assert.match(workflowSource, /aria-current="step\.id === current\.id \? 'step' : undefined"/)
  assert.match(workflowSource, /下一步/)
  assert.match(workflowSource, /@media \(max-width: 820px\)/)
  assert.match(workflowSource, /overflow-x: auto/)
})
