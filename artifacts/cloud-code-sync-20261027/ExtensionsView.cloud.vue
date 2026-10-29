<template>
  <div class="extensions-view extension-page-root">
    <PageHeader
      v-if="!isDetailPage"
      v-model:active-key="activeTab"
      title="智能体扩展"
      :tabs="extensionTabs"
      :loading="activeChildLoading"
      :show-border="true"
      aria-label="智能体扩展视图切换"
    />

    <nav
      v-if="!isDetailPage && activeTab === 'knowledge'"
      class="knowledge-sections"
      aria-label="知识库功能"
    >
      <RouterLink
        to="/extensions"
        :aria-current="!wxChannelsActive && !wechatArticlesActive ? 'page' : undefined"
      >
        <BookOpen :size="16" />资料库
      </RouterLink>
      <RouterLink
        :to="{ path: '/extensions', query: { tool: 'wxchannels' } }"
        :aria-current="wxChannelsActive ? 'page' : undefined"
      >
        <Film :size="16" />视频号转 DOCX
      </RouterLink>
      <RouterLink
        :to="{ path: '/extensions', query: { tool: 'wechat-articles' } }"
        :aria-current="wechatArticlesActive ? 'page' : undefined"
      >
        <Newspaper :size="16" />公众号文章
      </RouterLink>
    </nav>

    <div v-if="!isDetailPage" class="extensions-content">
      <div v-if="activeTab === 'knowledge'" class="tab-panel">
        <WxChannelsView v-if="wxChannelsActive" />
        <WechatArticlesView v-else-if="wechatArticlesActive" />
        <DataBaseView v-else ref="knowledgeRef" embedded />
      </div>
      <div v-if="userStore.isAdmin && activeTab === 'tools'" class="tab-panel">
        <ToolsCardList ref="toolsRef" />
      </div>
      <div v-if="activeTab === 'skills'" class="tab-panel">
        <SkillCardList ref="skillsRef" />
      </div>
      <div v-if="userStore.isAdmin && activeTab === 'mcp'" class="tab-panel">
        <McpCardList ref="mcpRef" />
      </div>
    </div>

    <router-view v-else :key="route.path" />
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { BookOpen, Film, Newspaper } from '@lucide/vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import AsyncViewError from '@/components/shared/AsyncViewError.vue'
import { useUserStore } from '@/stores/user'

const ToolsCardList = defineAsyncComponent({
  loader: () => import('@/components/extensions/ToolsCardList.vue'),
  errorComponent: AsyncViewError,
  timeout: 20000
})
const McpCardList = defineAsyncComponent({
  loader: () => import('@/components/extensions/McpCardList.vue'),
  errorComponent: AsyncViewError,
  timeout: 20000
})
const SkillCardList = defineAsyncComponent({
  loader: () => import('@/components/extensions/SkillCardList.vue'),
  errorComponent: AsyncViewError,
  timeout: 20000
})
const DataBaseView = defineAsyncComponent({
  loader: () => import('@/views/DataBaseView.vue'),
  errorComponent: AsyncViewError,
  timeout: 20000
})
const WxChannelsView = defineAsyncComponent({
  loader: () => import('@/views/WxChannelsView.vue'),
  errorComponent: AsyncViewError,
  timeout: 20000
})
const WechatArticlesView = defineAsyncComponent({
  loader: () => import('@/views/WechatArticlesView.vue'),
  errorComponent: AsyncViewError,
  timeout: 20000
})
const wechatArticlesActive = computed(() => route.query.tool === 'wechat-articles')
const wxChannelsActive = computed(() => route.query.tool === 'wxchannels')
const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const activeTab = ref(null)
const knowledgeRef = ref(null)
const skillsRef = ref(null)
const mcpRef = ref(null)
const toolsRef = ref(null)

const adminExtensionTabs = computed(() => [
  { key: 'knowledge', label: '知识库' },
  { key: 'skills', label: '技能' },
  { key: 'tools', label: '工具' },
  { key: 'mcp', label: 'MCP' }
])
const userExtensionTabs = [
  { key: 'knowledge', label: '知识库' },
  { key: 'skills', label: '技能' }
]
const extensionTabs = computed(() =>
  userStore.isAdmin ? adminExtensionTabs.value : userExtensionTabs
)
const allowedTabKeys = computed(() => extensionTabs.value.map((tab) => tab.key))
const defaultTabKey = computed(() => extensionTabs.value[0]?.key || 'skills')

const normalizeTab = (tab) => {
  if (allowedTabKeys.value.includes(tab)) return tab
  return defaultTabKey.value
}

const replaceTabQuery = (tab) => {
  const query = { ...route.query }
  if (tab !== 'knowledge') {
    delete query.tool
    delete query.kb
  }
  if (tab === defaultTabKey.value) {
    delete query.tab
  } else {
    query.tab = tab
  }
  router.replace({ query })
}

const isDetailPage = computed(() => {
  return (
    route.path.startsWith('/extensions/knowledgebase/') ||
    route.path.startsWith('/extensions/mcp/') ||
    route.path.startsWith('/extensions/skill/')
  )
})

const activeChildLoading = computed(() => {
  const refMap = {
    knowledge: knowledgeRef,
    tools: toolsRef,
    skills: skillsRef,
    mcp: mcpRef
  }
  const child = refMap[activeTab.value]
  return child?.value?.loading || false
})

watch(
  () => [route.query.tab, userStore.isAdmin],
  ([tab]) => {
    const nextTab = normalizeTab(tab)
    if (activeTab.value !== nextTab) activeTab.value = nextTab
    if (tab && tab !== nextTab) replaceTabQuery(nextTab)
  },
  { immediate: true }
)

watch(activeTab, (tab) => {
  if (!tab) return
  const nextTab = normalizeTab(tab)
  if (nextTab !== tab) {
    activeTab.value = nextTab
    return
  }
  if (route.query.tab === nextTab || (!route.query.tab && nextTab === defaultTabKey.value)) return
  replaceTabQuery(nextTab)
})
</script>

<style scoped lang="less">
@import '@/assets/css/extensions.less';

.knowledge-sections {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px var(--page-padding);
  border-bottom: 1px solid var(--gray-100);

  a {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 7px 12px;
    border-radius: 8px;
    color: var(--gray-700);
    font-size: 13px;
    text-decoration: none;

    &:hover {
      background: var(--gray-50);
    }
    &[aria-current='page'] {
      background: var(--main-50);
      color: var(--main-800);
    }
    &:focus-visible {
      outline: 2px solid var(--main-color);
      outline-offset: 2px;
    }
  }
}

.extensions-view {
  .extensions-content {
    flex: 1;
    min-height: 0;
    overflow: hidden;

    .tab-panel {
      height: 100%;
      min-height: 0;
      overflow-y: auto;
    }
  }
}
</style>
