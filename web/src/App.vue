<script setup>
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { ConfigProvider as AConfigProvider } from 'ant-design-vue'
import { useThemeStore } from '@/stores/theme'
import SiteFooter from '@/components/SiteFooter.vue'

const themeStore = useThemeStore()
</script>
<template>
  <a-config-provider :theme="themeStore.currentTheme" :locale="zhCN">
    <router-view />
    <SiteFooter />
  </a-config-provider>
</template>
