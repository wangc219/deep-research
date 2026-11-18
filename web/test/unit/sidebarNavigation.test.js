import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../../src/layouts/AppLayout.vue', import.meta.url), 'utf8')
const loginSource = readFileSync(new URL('../../src/views/LoginView.vue', import.meta.url), 'utf8')
const oidcCallbackSource = readFileSync(
  new URL('../../src/views/OIDCCallbackView.vue', import.meta.url),
  'utf8'
)
const oidcRedirectSource = readFileSync(
  new URL('../../src/utils/oidcAutoStart.js', import.meta.url),
  'utf8'
)

test('侧边栏常驻五个普通用户高频入口', () => {
  const primaryNames = ['智能对话', '研究任务', '深研对话', '能力画像', '收藏']

  for (const name of primaryNames) {
    assert.match(
      source,
      new RegExp(`name: '${name}'[\\s\\S]{0,260}?primary: true`),
      `${name} 应保持常驻`
    )
  }
  assert.match(source, /const primaryNavItems = computed\(\(\) => mainList\.value\.filter/)
  assert.match(source, /'primary-action': item\.primaryAction/)
})

test('低频入口默认收进更多功能，当前页面在折叠区时自动展开', () => {
  for (const name of [
    '知识总览',
    '需求 Query',
    '研究报告',
    '个人空间',
    '智能体',
    '知识库 · 技能'
  ]) {
    assert.match(source, new RegExp(`name: '${name}'`))
  }
  assert.match(source, /const exploratoryNavItems = computed/)
  assert.match(source, /const isExploreRouteActive = computed/)
  assert.match(
    source,
    /const exploreNavOpen = computed\(\(\) => exploreNavRequestedOpen\.value \|\| isExploreRouteActive\.value\)/
  )
  assert.match(source, /aria-controls="exploratory-navigation"/)
  assert.match(source, />更多功能<\/span>/)
  assert.match(source, /aria-label="更多与探索性功能"/)
})

test('无指定回跳目标时以智能对话作为登录后主入口', () => {
  assert.match(loginSource, /sessionStorage\.getItem\('redirect'\) \|\| '\/agent'/)
  assert.match(loginSource, /redirectPath === '\/' \? '\/agent' : redirectPath/)
  assert.match(oidcCallbackSource, /getItem\('oidc_redirect'\) \|\| '\/agent'/)
  assert.match(oidcCallbackSource, /router\.push\('\/agent'\)/)
  assert.match(oidcRedirectSource, /return '\/agent'/)
})
