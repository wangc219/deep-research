import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

test('企业管理保留企业用户卡片和创建入口且不展示租户文案', () => {
  const enterpriseView = readFileSync(
    new URL('../../src/views/EnterpriseView.vue', import.meta.url),
    'utf8'
  )

  assert.match(enterpriseView, /用户与部门/)
  assert.match(enterpriseView, /企业用户/)
  assert.match(enterpriseView, /新用户名称/)
  assert.match(enterpriseView, /function addTenant/)
  assert.match(enterpriseView, /function openTenantEditor/)
  assert.match(enterpriseView, /function saveTenant/)
  assert.match(enterpriseView, /deleteTenant/)
  assert.match(enterpriseView, /编辑企业用户/)
  assert.match(enterpriseView, /部门组织架构/)
  assert.match(enterpriseView, /同时创建部门管理员/)
  assert.match(enterpriseView, /create_admin: false/)
  assert.match(enterpriseView, /function openDepartmentEditor/)
  assert.match(enterpriseView, /function saveDepartment/)
  assert.match(enterpriseView, /上级部门/)
  assert.match(enterpriseView, /不能选择当前部门或它的下级部门/)
  assert.match(enterpriseView, /deleteDepartment/)
  assert.match(enterpriseView, /部门管理员可管理本部门及全部下级部门/)
  assert.match(enterpriseView, /兄弟部门和上级部门仍保持隔离/)
  assert.match(enterpriseView, /v-if="user\.isAdmin" class="department-form"/)
  assert.match(
    enterpriseView,
    /department\.parent_id \?\? \(user\.isSuperAdmin \? null : user\.departmentId\)/
  )
  assert.match(enterpriseView, /全体用户/)
  assert.doesNotMatch(enterpriseView, /企业租户|租户与部门|新租户名称|暂无租户|此租户/)
})
