<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { RefreshCw, WifiOff } from '@lucide/vue'
import { sanitizeRedirect } from '@/utils/oidcAutoStart'

const route = useRoute()
const router = useRouter()
const retrying = ref(false)
const retry = async () => {
  retrying.value = true
  try {
    const target = sanitizeRedirect(route.query.redirect)
    await router.replace(target.startsWith('/connection-error') ? '/knowledge' : target)
  } finally {
    retrying.value = false
  }
}
</script>

<template>
  <main class="connection-recovery" aria-labelledby="connection-title">
    <WifiOff :size="32" aria-hidden="true" />
    <h1 id="connection-title">暂时无法连接服务</h1>
    <p>登录状态与草稿已保留。请检查网络，或稍后重试。</p>
    <button type="button" :disabled="retrying" @click="retry">
      <RefreshCw :size="16" aria-hidden="true" />{{ retrying ? '正在重连…' : '重新连接' }}
    </button>
  </main>
</template>

<style scoped>
.connection-recovery {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 16px;
  padding: 24px;
  text-align: center;
  color: var(--gray-700);
  background: var(--gray-25);
}
.connection-recovery > svg {
  color: var(--main-color);
}
h1 {
  margin: 0;
  font-size: 24px;
  color: var(--gray-900);
}
p {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
}
button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  border: 1px solid var(--main-color);
  border-radius: 10px;
  background: var(--main-color);
  color: var(--gray-0);
  cursor: pointer;
}
button:disabled {
  opacity: 0.6;
  cursor: wait;
}
button:focus-visible {
  outline: 2px solid var(--main-color);
  outline-offset: 4px;
}
</style>
