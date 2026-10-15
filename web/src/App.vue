<script setup>
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { useAgentStore } from '@/stores/agent'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import SiteFooter from '@/components/SiteFooter.vue'

const agentStore = useAgentStore()
const userStore = useUserStore()
const themeStore = useThemeStore()
const route = useRoute()

onMounted(async () => {
  if (!/^\/document-research\/?$/.test(window.location.pathname) && route.name !== 'DocumentResearch' && userStore.isLoggedIn) {
    await agentStore.initialize()
  }
})
</script>
<template>
  <a-config-provider :theme="themeStore.currentTheme" :locale="zhCN">
    <router-view />
    <SiteFooter />
  </a-config-provider>
</template>
