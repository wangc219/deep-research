import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

test('前端将 admin 作为全局业务管理员并保留超级管理员身份治理边界', () => {
  const userStore = readFileSync(new URL('../../src/stores/user.js', import.meta.url), 'utf8')
  const userManagement = readFileSync(
    new URL('../../src/components/UserManagementComponent.vue', import.meta.url),
    'utf8'
  )
  const layout = readFileSync(new URL('../../src/layouts/AppLayout.vue', import.meta.url), 'utf8')
  const router = readFileSync(new URL('../../src/router/index.js', import.meta.url), 'utf8')

  assert.match(userStore, /userRole\.value === 'admin' \|\| userRole\.value === 'superadmin'/)
  assert.match(userStore, /previousRole !== userData\.role[\s\S]*?useEquipmentStore\(\)\.reset\(\)/)
  assert.match(userManagement, /提升为管理员后立即获得全局业务资源权限/)
  assert.match(userManagement, /角色治理仍仅限超级管理员；部门管理员可治理自己的部门子树/)
  assert.match(userManagement, /userStore\.isSuperAdmin[\s\S]*?updateData\.role/)
  assert.match(userManagement, /label="用户ID"/)
  assert.match(userManagement, /updateData\.uid = userManagement\.form\.uid\.trim\(\)/)
  assert.match(userManagement, /userManagement\.editUserId === userStore\.userId/)
  assert.match(layout, /SESSION_ROLE_SYNC_INTERVAL_MS/)
  assert.match(layout, /await userStore\.getCurrentUser\(\)/)
  assert.match(layout, /userStore\.isAdmin[\s\S]*?path: '\/dashboard'/)
  assert.match(router, /name: 'DashboardComp'[\s\S]*?requiresAdmin: true/)
})
