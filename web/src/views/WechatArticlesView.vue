<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { RefreshCw, Archive, Newspaper } from '@lucide/vue'
import CollectionArtifactsPanel from '@/components/knowledge/CollectionArtifactsPanel.vue'
import { wechatMpApi } from '@/apis/wechat_mp_api'

const frame = ref(null)
const tab = ref('collect')
const artifactCount = ref(0)
const source = ref('')
const loading = ref(false)
const error = ref('')
async function connect() {
  loading.value = true
  error.value = ''
  source.value = ''
  try {
    const session = await wechatMpApi.openSession()
    source.value = session.document || (await wechatMpApi.document())
  } catch (cause) {
    error.value = cause.message || '公众号服务连接失败，请重试。'
  } finally {
    loading.value = false
  }
}
function sessionExpired(event) {
  if (event.origin !== window.location.origin || event.source !== frame.value?.contentWindow) return
  if (event.data?.type === 'wechat-mp-session-expired') {
    error.value = '平台会话已过期，请重新登录后连接。'
    source.value = ''
  }
}
onMounted(() => {
  window.addEventListener('message', sessionExpired)
  connect()
})
onUnmounted(() => window.removeEventListener('message', sessionExpired))
</script>

<template>
  <section class="wechat-articles" aria-label="公众号文章">
    <nav class="module-tabs" aria-label="公众号工作流程">
      <button :class="{ active: tab === 'collect' }" @click="tab = 'collect'">
        <Newspaper :size="16" />采集与下载
      </button>
      <button :class="{ active: tab === 'results' }" @click="tab = 'results'">
        <Archive :size="16" />沙盒成果与入库<span v-if="artifactCount">{{ artifactCount }}</span>
      </button>
      <p>批量选择文章 → 下载到沙盒工作区 → 按需选择入库</p>
    </nav>
    <div v-show="tab === 'collect'" class="module-collector">
      <div v-if="loading" class="module-state" role="status">
        <a-spin />
        <p>正在连接公众号文章…</p>
      </div>
      <div v-else-if="error" class="module-state" role="alert">
        <h3>公众号文章暂时无法连接</h3>
        <p>{{ error }}</p>
        <a-button @click="connect"><RefreshCw :size="15" />重新连接</a-button>
      </div>
      <iframe
        v-else-if="source"
        ref="frame"
        :srcdoc="source"
        title="微信公众号文章管理"
        class="module-frame"
        referrerpolicy="same-origin"
      />
    </div>
    <div v-if="tab === 'results'" class="module-results">
      <CollectionArtifactsPanel source="wechat-articles" @count="artifactCount = $event" />
    </div>
  </section>
</template>

<style scoped>
.wechat-articles {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 580px;
  background: var(--gray-0);
}
.module-collector {
  flex: 1;
  min-height: 580px;
}
.module-results {
  padding: 24px;
  overflow: auto;
}
.module-tabs {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 12px 20px;
  border-bottom: 1px solid var(--gray-200);
}
.module-tabs button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--gray-700);
  cursor: pointer;
}
.module-tabs button.active {
  color: var(--main-800);
  background: var(--main-50);
}
.module-tabs p {
  margin: 0 0 0 auto;
  font-size: 12px;
  color: var(--gray-600);
}
.module-frame {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 580px;
  border: 0;
}
.module-state {
  display: grid;
  place-content: center;
  justify-items: center;
  min-height: 420px;
  gap: 16px;
  color: var(--gray-600);
}
.module-state button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
</style>
