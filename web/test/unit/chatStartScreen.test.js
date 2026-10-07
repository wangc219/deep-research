import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as Vue from 'vue'
import { renderToString } from 'vue/server-renderer'

const source = readFileSync(
  new URL('../../src/components/AgentChatComponent.vue', import.meta.url),
  'utf8'
)
const view = readFileSync(new URL('../../src/views/AgentView.vue', import.meta.url), 'utf8')
const appLayout = readFileSync(new URL('../../src/layouts/AppLayout.vue', import.meta.url), 'utf8')
const runsView = readFileSync(
  new URL('../../src/views/equipment/EquipmentRunsView.vue', import.meta.url),
  'utf8'
)
const mainStyles = readFileSync(new URL('../../src/assets/css/main.css', import.meta.url), 'utf8')
const dock = source.slice(
  source.indexOf('<div\n            ref="messageInputDockRef"'),
  source.indexOf('              <section\n                v-if="currentQueuedRequests.length"')
)
const render = Vue.compile(`${dock}</div></div>`)

test('路由决定新建布局，已有线程的加载和空消息不显示居中输入框或欢迎语', async () => {
  assert.ok(view.includes(':is-new-conversation="!getRouteThreadId()"'), '新建布局由路由传入')
  for (const isNewConversation of [false, true]) {
    for (const isLoadingMessages of [false, true]) {
      for (const conversations of [[], [{ id: 'history' }]]) {
        const html = await renderToString(
          Vue.createSSRApp({
            data: () => ({
              isNewConversation,
              isLoadingMessages,
              conversations,
              randomGreeting: '欢迎测试'
            }),
            render
          })
        )
        assert.equal(html.includes('start-screen'), isNewConversation)
        assert.equal(html.includes('欢迎测试'), isNewConversation)
        assert.equal(html.includes('正在加载消息'), isLoadingMessages)
      }
    }
  }
})

test('所有主导航页面共用淡蓝装备背景，智能对话与研究任务共用主题标题样式', () => {
  assert.match(appLayout, /url\('\/equipment-login-hero\.png'\) center \/ cover no-repeat/)
  assert.match(appLayout, /rgba\(242, 248, 255, 0\.86\)/)
  assert.equal(appLayout.match(/class="app-navigation-page"/g)?.length, 2)
  assert.match(mainStyles, /\.app-navigation-page\s*\{[\s\S]*?background:\s*transparent !important/)
  assert.match(
    mainStyles,
    /html\.dark #app-router-view\s*\{[\s\S]*?rgba\(14, 19, 31, 0\.88\)/
  )
  assert.match(
    mainStyles,
    /html\.dark \.app-navigation-page :where\([\s\S]*?textarea,[\s\S]*?select,[\s\S]*?\.ant-input-affix-wrapper,[\s\S]*?\.ant-select:not\(\.ant-select-customize-input\) \.ant-select-selector[\s\S]*?background-color:\s*#141925 !important/
  )
  assert.match(
    mainStyles,
    /html\.dark \.app-navigation-page :where\([\s\S]*?\.research-query-composer,[\s\S]*?\.research-mode-menu,[\s\S]*?\.research-runtime-panel,[\s\S]*?\.runtime-slot-grid article[\s\S]*?background:\s*#141925 !important/
  )
  assert.match(
    mainStyles,
    /html\.dark \.app-navigation-page :where\([\s\S]*?\.recommendation-card,[\s\S]*?\.recommendation-card\.current[\s\S]*?background:\s*rgba\(20, 25, 37, 0\.94\) !important/
  )
  assert.match(
    mainStyles,
    /html\.dark \.app-navigation-page :where\([\s\S]*?\.workspace-pulse,[\s\S]*?\.research-run-center[\s\S]*?background:\s*rgba\(17, 22, 34, 0\.92\) !important/
  )
  assert.match(
    mainStyles,
    /html\.dark \.app-navigation-page :where\([\s\S]*?\.filter-select,[\s\S]*?\.research-run-card,[\s\S]*?\.run-card-artifacts button[\s\S]*?background:\s*#171d2a !important/
  )
  assert.match(
    mainStyles,
    /html\.dark \.app-navigation-page :where\([\s\S]*?\.deep-sidebar,[\s\S]*?\.deep-session-list,[\s\S]*?\.deep-history-group-toggle[\s\S]*?background:\s*#141925 !important/
  )
  assert.match(
    mainStyles,
    /html\.dark \.app-navigation-page :where\([\s\S]*?\.workspace-stage-nav,[\s\S]*?\.task-review-rail,[\s\S]*?\.task-review-content[\s\S]*?background:\s*rgba\(17, 22, 34, 0\.94\) !important/
  )
  assert.match(
    mainStyles,
    /html\.dark \.app-navigation-page :where\([\s\S]*?\.favorite-module,[\s\S]*?\.favorite-card-actions button,[\s\S]*?\.favorite-reader-nav[\s\S]*?background:\s*#171d2a !important/
  )
  assert.match(
    mainStyles,
    /html\.dark \.app-navigation-page \.run-card-capability-preview\s*\{[\s\S]*?background:\s*#242b3c !important/
  )
  assert.match(
    mainStyles,
    /html\.dark \.app-navigation-page :where\([\s\S]*?\.capability-toolbar,[\s\S]*?\.capability-sheet,[\s\S]*?\.capability-portrait-card,[\s\S]*?\.deep-research-comparison[\s\S]*?background:\s*#141925 !important/
  )
  assert.match(
    mainStyles,
    /html\.dark \.app-navigation-page :where\([\s\S]*?\.favorite-modules button,[\s\S]*?\.reader,[\s\S]*?\.reader-nav[\s\S]*?background:\s*#171d2a !important/
  )
  assert.match(source, /<h1 class="research-theme-title">\{\{ randomGreeting \}\}<\/h1>/)
  assert.match(source, /const randomGreeting = '智启新境 · 探索装备未来'/)
  assert.match(runsView, /<h1 class="research-theme-title">创新为帆 探索未至之境<\/h1>/)
  assert.match(
    mainStyles,
    /\.research-theme-title\s*\{[\s\S]*?color:\s*#33377f[\s\S]*?font-size:\s*29px[\s\S]*?font-weight:\s*700/
  )
  assert.match(mainStyles, /html\.dark \.research-theme-title\s*\{[\s\S]*?color:\s*#d9ddff/)
})
