import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'

import App from './App.vue'
import router from './router'

import 'ant-design-vue/dist/reset.css'
import '@/assets/css/main.css'

const app = createApp(App)
const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)

app.use(pinia)
app.use(router)

// 预加载信息配置
import { useInfoStore } from '@/stores/info'
const infoStore = useInfoStore()
// 专用入口无需平台服务；直接加载时不读取平台配置或会话。
if (!/^\/document-research\/?$/.test(window.location.pathname)) infoStore.loadInfoConfig()

app.mount('#app')
