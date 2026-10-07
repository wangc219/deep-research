import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { routeViewKey } from '../../src/utils/routeViewKey.js'

test('已迁移的装备页面使用独立 Vue 视图实例', () => {
  assert.equal(routeViewKey({ path: '/equipment/deep-thinking' }), 'equipment-deep-thinking')
  assert.equal(
    routeViewKey({ path: '/equipment/deep-thinking/session-1' }),
    'equipment-deep-thinking'
  )
  assert.equal(routeViewKey({ path: '/equipment/favorites' }), 'equipment-favorites')
  assert.equal(routeViewKey({ path: '/equipment/queries' }), 'equipment-queries')
  assert.equal(routeViewKey({ path: '/equipment/runs' }), 'equipment-runs')
  assert.equal(routeViewKey({ path: '/equipment/capabilities' }), 'equipment-capabilities')
  assert.equal(routeViewKey({ path: '/equipment/reports' }), 'equipment-reports')
  assert.equal(routeViewKey({ path: '/equipment/runs/run-1' }), 'equipment-run-detail')
  assert.equal(routeViewKey({ path: '/agent' }), 'agent-workspace')
  assert.equal(routeViewKey({ path: '/agent/thread-1' }), 'agent-workspace')
  assert.equal(routeViewKey({ path: '/agent/thread-2' }), 'agent-workspace')
  assert.equal(routeViewKey({ path: '/dashboard' }), '/dashboard')
})

test('布局导航不再触发旧深研浮层', () => {
  const source = readFileSync(new URL('../../src/layouts/AppLayout.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /equipment:open-deep-thinking/)
  assert.doesNotMatch(source, /handleNavItemClick/)
})

test('缓存中的智能对话页不会抢占深研会话路由', () => {
  const agentView = readFileSync(new URL('../../src/views/AgentView.vue', import.meta.url), 'utf8')

  assert.match(agentView, /const isAgentRoute = \(\) =>/)
  assert.match(
    agentView,
    /const syncSelectedThreadFromRoute = async \(\) => \{[\s\S]*?if \(!isAgentRoute\(\)\) return/
  )
  assert.match(
    agentView,
    /const handleThreadChange = \(threadId\) => \{\s*if \(!isAgentRoute\(\)\) return/
  )
  assert.match(agentView, /\[\(\) => route\.path, \(\) => route\.params\.thread_id\]/)
})

test('装备正式路由不再挂载 React 工作台宿主', () => {
  const router = readFileSync(new URL('../../src/router/index.js', import.meta.url), 'utf8')
  const vite = readFileSync(new URL('../../vite.config.js', import.meta.url), 'utf8')
  assert.doesNotMatch(router, /EquipmentWorkbenchHost/)
  assert.doesNotMatch(vite, /plugin-react/)
  assert.doesNotMatch(vite, /react\/jsx-runtime/)
})

test('装备深研复用平台原生聊天内核并保留领域扩展槽位', () => {
  const deepView = readFileSync(
    new URL('../../src/views/equipment/EquipmentDeepThinkingView.vue', import.meta.url),
    'utf8'
  )
  const nativeChat = readFileSync(
    new URL('../../src/components/AgentChatComponent.vue', import.meta.url),
    'utf8'
  )

  assert.match(deepView, /<AgentChatComponent/)
  assert.match(deepView, /:run-meta="deepRunMeta"/)
  assert.match(deepView, /#message-actions/)
  assert.match(deepView, /equipment_create_artifact/)
  assert.doesNotMatch(deepView, /setInterval/)
  assert.match(nativeChat, /name="message-actions"/)
  assert.match(nativeChat, /runMeta/)
  assert.match(nativeChat, /run-submitted/)
})

test('研究焦点区分绑定装备深化与显式新质发散', () => {
  const deepView = readFileSync(
    new URL('../../src/views/equipment/EquipmentDeepThinkingView.vue', import.meta.url),
    'utf8'
  )
  const seedSource = readFileSync(
    new URL('../../src/utils/equipmentDeepPortraitSections.js', import.meta.url),
    'utf8'
  )

  assert.match(deepView, /research_mode === 'section_deepen'/)
  assert.match(deepView, /research_mode === 'new_weapon_diverge'/)
  assert.match(deepView, /不预设单一装备形态、技术路线或固定结论/)
  assert.match(deepView, /'研究焦点（锁定装备）'\s*:\s*'研究焦点（开放发散）'/)
  assert.match(seedSource, /保持装备身份不变/)
  assert.match(seedSource, /关键技术卡点、工程痛点、指标耦合和系统集成难题/)
  assert.match(seedSource, /证据缺口、失效边界和验证动作只在确实影响方案成立或研发决策时补充/)
  assert.match(seedSource, /显式切换到新质发散模式才生成新装备候选/)
  assert.match(seedSource, /允许突破原装备身份、任务链与作用机理/)
})

test('深研历史会话按 Query 分组并区分当前与归档', () => {
  const deepView = readFileSync(
    new URL('../../src/views/equipment/EquipmentDeepThinkingView.vue', import.meta.url),
    'utf8'
  )
  const history = readFileSync(
    new URL('../../src/components/equipment/EquipmentDeepSessionHistory.vue', import.meta.url),
    'utf8'
  )

  assert.match(deepView, /const sessionsLoading = ref\(true\)/)
  assert.match(deepView, /<EquipmentDeepSessionHistory/)
  assert.match(history, /class="deep-session-history-scroll"/)
  assert.match(deepView, /const sessionSwitching = ref\(false\)/)
  assert.match(deepView, /class="deep-session-switch-layer"/)
  assert.match(deepView, /--deep-sidebar-width: clamp\(248px, 19vw, 288px\)/)
  assert.match(deepView, /max-width: min\(1120px, calc\(100% - 32px\)\)/)
  assert.match(deepView, /const conversationFocusMode = ref\(readConversationFocusMode\(\)\)/)
  assert.match(deepView, /const researchControlOpen = ref\(false\)/)
  assert.match(deepView, /class="focus-research-trigger"/)
  assert.match(deepView, /class="research-control-popover"/)
  assert.match(deepView, /先选择研究目标，再选择下一步；所有动作都会先填入输入框/)
  assert.match(deepView, /查看研究全景/)
  assert.match(deepView, /返回专注对话/)
  assert.doesNotMatch(deepView, /#above-input/)
  assert.match(deepView, /v-if="!conversationFocusMode" class="research-summary"/)
  assert.match(deepView, /v-show="!conversationFocusMode" class="deep-domain-projection"/)
  assert.match(deepView, /当前对话已保留/)
  assert.doesNotMatch(
    deepView,
    /const loadSession = async \(\) => \{[\s\S]*?session\.value = null[\s\S]*?if \(!requestedSessionId\)/
  )
  assert.match(
    history,
    /:aria-current="selectedSessionId === item\.session_id \? 'page' : undefined"/
  )
  assert.match(history, /pendingSessionId === item\.session_id/)
  assert.match(history, /当前 \{\{ currentSessions\.length \}\}/)
  assert.match(history, /归档 \{\{ archivedSessions\.length \}\}/)
  assert.match(history, /deep-history-group-sessions/)
  assert.match(history, /删除后无法恢复/)
  assert.match(deepView, /sessionsLoading\.value = false/)
  assert.match(
    deepView,
    /@media \(max-width: 960px\)[\s\S]*?\.deep-research-shell \{[\s\S]*?flex-direction: column;[\s\S]*?\.deep-sidebar \{[\s\S]*?height: 88px;[\s\S]*?max-height: 88px;[\s\S]*?flex: 0 0 88px;/
  )
  assert.match(
    deepView,
    /@media \(max-width: 960px\)[\s\S]*?\.deep-main \{[\s\S]*?min-height: 0;[\s\S]*?flex: 1 1 0;/
  )
  assert.match(
    deepView,
    /@media \(max-width: 720px\)[\s\S]*?height: 80px;[\s\S]*?max-height: 80px;[\s\S]*?flex-basis: 80px;/
  )
  assert.match(
    history,
    /@media \(max-width: 960px\)[\s\S]*?\.deep-session-list \{[\s\S]*?max-height: 88px;[\s\S]*?overflow: hidden;/
  )
  assert.match(
    history,
    /\.deep-session-history-scroll \{[\s\S]*?overflow-x: hidden;[\s\S]*?overflow-y: auto;/
  )
  assert.doesNotMatch(deepView, /mobileSidebarOpen|mobile-open|deep-sidebar-scrim/)
})

test('研究任务与深研对话共享 run 上下文并提供双向入口', () => {
  const deepView = readFileSync(
    new URL('../../src/views/equipment/EquipmentDeepThinkingView.vue', import.meta.url),
    'utf8'
  )
  const runsView = readFileSync(
    new URL('../../src/views/equipment/EquipmentRunsView.vue', import.meta.url),
    'utf8'
  )

  assert.match(deepView, /form\.value\.run_id = requestedRun\.run_id/)
  assert.match(deepView, /class="linked-run-banner"/)
  assert.match(deepView, /返回研究任务/)
  assert.match(deepView, /openRunWorkspace\('capabilities'\)/)
  assert.match(deepView, /query: runId \? \{ run: runId \} : \{\}/)
  assert.match(runsView, /artifactCount\(run, 'deep_sessions'\)/)
  assert.match(runsView, /继续深研.*发起深研/)
  assert.match(runsView, /openArtifact\(run, 'deep-thinking'\)/)
  assert.match(runsView, /\/equipment\/deep-thinking\?run=/)
})

test('Vue 装备工作台不再从 React 工程加载运行时资源', () => {
  const vite = readFileSync(new URL('../../vite.config.js', import.meta.url), 'utf8')
  const sources = [
    'EquipmentRunsView.vue',
    'EquipmentDeepThinkingView.vue',
    'EquipmentCapabilitiesView.vue',
    'EquipmentReportsView.vue',
    'EquipmentRunDetailView.vue'
  ].map((name) =>
    readFileSync(new URL(`../../src/views/equipment/${name}`, import.meta.url), 'utf8')
  )

  assert.doesNotMatch(vite, /legacy-workbench|apps\/web\/src/)
  for (const source of sources) assert.doesNotMatch(source, /@legacy-workbench|apps\/web\/src/)
  assert.match(sources.join('\n'), /equipment-workbench-live\.css/)
  assert.match(sources.join('\n'), /equipment-workbench-theme\.css/)
})

test('共享工作台主题通过脚本全局导入，不能被 Vue 外部样式误编译为单页作用域', () => {
  for (const name of [
    'EquipmentRunsView.vue',
    'EquipmentRunDetailView.vue',
    'EquipmentCapabilitiesView.vue',
    'EquipmentReportsView.vue'
  ]) {
    const source = readFileSync(
      new URL(`../../src/views/equipment/${name}`, import.meta.url),
      'utf8'
    )
    assert.match(source, /import ['"]@\/assets\/css\/equipment-workbench-theme\.css['"]/)
    assert.doesNotMatch(source, /<style\s+src=['"]@\/assets\/css\/equipment-workbench-theme\.css/)
    assert.doesNotMatch(source, /<style\s+src=['"]@\/assets\/css\/equipment-workbench-live\.css/)
  }
})
