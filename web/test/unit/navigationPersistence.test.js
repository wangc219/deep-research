import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = (path) => readFile(new URL(path, import.meta.url), 'utf8')

test('主导航在同一缓存边界内切换，不销毁已打开的工作区', async () => {
  const layout = await source('../../src/layouts/AppLayout.vue')
  assert.match(layout, /<keep-alive>\s*<component\s*:is="route\.meta\.keepAlive !== false \? Component : null"/)
  assert.match(layout, /v-if="route\.meta\.keepAlive === false"/)
  assert.match(layout, /@pointerenter="preloadNavItem\(item\)"/)
})

test('装备研究全部路由使用独立 Vue 页面并保持缓存', async () => {
  const router = await source('../../src/router/index.js')
  const equipmentRouteBlock = router.slice(router.indexOf("path: '/equipment'"), router.indexOf("path: '/agent'"))

  assert.equal((equipmentRouteBlock.match(/keepAlive: true/g) || []).length, 8)
  assert.doesNotMatch(equipmentRouteBlock, /keepAlive: false/)
  assert.match(equipmentRouteBlock, /EquipmentDeepThinkingView\.vue/)
  assert.match(equipmentRouteBlock, /EquipmentRunsView\.vue/)
  assert.match(equipmentRouteBlock, /EquipmentRunDetailView\.vue/)
  assert.match(equipmentRouteBlock, /EquipmentQueriesView\.vue/)
  assert.match(equipmentRouteBlock, /EquipmentCapabilitiesView\.vue/)
  assert.match(equipmentRouteBlock, /EquipmentReportsView\.vue/)
  assert.match(equipmentRouteBlock, /EquipmentFavoritesView\.vue/)
  assert.doesNotMatch(equipmentRouteBlock, /EquipmentWorkbenchHost\.vue/)
})
