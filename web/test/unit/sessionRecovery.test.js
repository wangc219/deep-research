import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'

const routerSource = readFileSync(new URL('../../src/router/index.js', import.meta.url), 'utf8')
const guardSource = routerSource.slice(
  routerSource.indexOf('router.beforeEach('),
  routerSource.indexOf('\nexport default router')
)

const createGuard = (status) => {
  let guard
  let logoutCount = 0
  let fetchCount = 0
  const store = {
    token: 'existing-session',
    userId: null,
    get isLoggedIn() {
      return Boolean(this.token)
    },
    async getCurrentUser() {
      fetchCount++
      throw Object.assign(new Error('unavailable'), { status })
    },
    logout() {
      logoutCount++
      this.token = ''
    }
  }
  vm.runInNewContext(guardSource, {
    router: {
      beforeEach: (callback) => {
        guard = callback
      }
    },
    useUserStore: () => store,
    console: { error() {} },
    sessionStorage: { setItem() {} },
    sanitizeRedirect: (path) => path || '/knowledge'
  })
  return { guard, store, logoutCount: () => logoutCount, fetchCount: () => fetchCount }
}
const target = {
  name: 'EquipmentDeepThinking',
  path: '/equipment/deep-thinking',
  fullPath: '/equipment/deep-thinking?run=sample',
  matched: [{ meta: { requiresAuth: true } }]
}

test('service outage preserves login and offers recovery to the original route', async () => {
  for (const status of [undefined, 500, 502, 503, 504]) {
    const state = createGuard(status)
    const result = await state.guard(target)
    assert.equal(result.name, 'ConnectionRecovery')
    assert.equal(result.query.redirect, target.fullPath)
    assert.equal(state.store.token, 'existing-session')
    assert.equal(state.logoutCount(), 0)
  }
})

test('401 still clears invalid authentication and redirects to login', async () => {
  const state = createGuard(401)
  assert.equal(await state.guard(target), '/login')
  assert.equal(state.logoutCount(), 1)
})

test('recovery page opens without looping over the unavailable profile request', async () => {
  const state = createGuard(503)
  assert.equal(
    await state.guard({ name: 'ConnectionRecovery', path: '/connection-error', matched: [] }),
    true
  )
  assert.equal(state.fetchCount(), 0)
})
