<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Keyboard, Search } from '@lucide/vue'

defineProps({
  title: { type: String, required: true },
  loading: { type: Boolean, default: false }
})

const commandKey = /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent || '')
  ? '⌘'
  : 'Ctrl'

const healthy = ref(false)
const runtime = ref({})

const onStatus = (event) => {
  healthy.value = Boolean(event.detail?.healthy)
  runtime.value = event.detail?.runtime || {}
}

onMounted(() => window.addEventListener('equipment:workbench-status', onStatus))
onBeforeUnmount(() => window.removeEventListener('equipment:workbench-status', onStatus))

const online = computed(() => healthy.value && Boolean(runtime.value.worker_online))

const statusLabel = computed(() => {
  if (!healthy.value) return '研究服务未连接'
  if (!runtime.value.worker_online) return 'Worker 未启动'
  const active = runtime.value.active_count || 0
  const capacity = runtime.value.worker_capacity || 0
  const pending = runtime.value.pending_count || 0
  return `并行 ${active}/${capacity} · 排队 ${pending}`
})

const statusTitle = computed(() => {
  if (!healthy.value) return '研究 API 未连接，请检查后端服务'
  if (!runtime.value.worker_online) return '请启动独立 research worker'
  const ids = runtime.value.active_run_ids || []
  return [
    `在线 Worker ${runtime.value.online_worker_count || 0} 个`,
    `可用槽位 ${runtime.value.available_slots || 0}`,
    `活动任务 ${ids.length ? ids.join('、') : '无'}`,
    `排队 ${runtime.value.pending_count || 0} 项`
  ].join('；')
})

const openPalette = () => window.dispatchEvent(new CustomEvent('equipment:open-command-palette'))
const openShortcuts = () => window.dispatchEvent(new CustomEvent('equipment:open-shortcuts'))
</script>

<template>
  <header class="ewh">
    <div v-if="loading" class="ewh-progress"><span /></div>

    <h1 class="ewh-title">{{ title }}</h1>

    <div class="ewh-actions">
      <button type="button" class="ewh-search" :title="`打开命令面板（${commandKey} + K）`" @click="openPalette">
        <Search :size="14" />
        <span>搜索任务、跳转视图…</span>
        <kbd>{{ commandKey }}</kbd><kbd>K</kbd>
      </button>

      <span class="ewh-status" :class="{ 'is-online': online }" :title="statusTitle">
        <i aria-hidden="true" />
        {{ statusLabel }}
      </span>

      <button
        type="button"
        class="ewh-icon-button"
        title="查看键盘快捷键（?）"
        aria-label="查看键盘快捷键"
        @click="openShortcuts"
      >
        <Keyboard :size="16" />
      </button>
    </div>
  </header>
</template>

<style scoped>
.ewh {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  gap: 16px;
  height: 48px;
  padding: 0 24px;
  border-bottom: 1px solid var(--gray-100, #e7eaf2);
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: saturate(1.4) blur(14px);
  -webkit-backdrop-filter: saturate(1.4) blur(14px);
}

.ewh-title {
  flex: 0 0 auto;
  margin: 0;
  color: var(--gray-900, #1e1f1f);
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
}

.ewh-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  margin-left: auto;
}

.ewh-search {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  min-width: 0;
  padding: 0 8px 0 10px;
  border: 1px solid var(--gray-150, #e3e5ec);
  border-radius: 8px;
  background: var(--gray-0, #fff);
  color: var(--gray-500, #8a8f9c);
  font-size: 12px;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease,
    color 0.15s ease;
}

.ewh-search:hover {
  border-color: var(--main-300, #b3b1f9);
  color: var(--gray-700, #4a4f5c);
}

.ewh-search span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ewh-search kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  border: 1px solid var(--gray-150, #e3e5ec);
  border-radius: 5px;
  background: var(--gray-25, #fafbfd);
  color: var(--gray-500, #8a8f9c);
  font-family: inherit;
  font-size: 10px;
}

.ewh-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 10px;
  border: 1px solid #f1dadd;
  border-radius: 999px;
  background: #fff7f7;
  color: #b4505b;
  font-size: 11px;
  white-space: nowrap;
}

.ewh-status.is-online {
  border-color: #dcece6;
  background: #f4fbf7;
  color: #2d8a62;
}

.ewh-status i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.ewh-icon-button {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid var(--gray-150, #e3e5ec);
  border-radius: 8px;
  background: var(--gray-0, #fff);
  color: var(--gray-600, #6b7280);
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    color 0.15s ease;
}

.ewh-icon-button:hover {
  border-color: var(--main-300, #b3b1f9);
  color: var(--main-color, #625ff0);
}

.ewh-progress {
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
  height: 2px;
  overflow: hidden;
}

.ewh-progress span {
  position: absolute;
  width: 30%;
  height: 100%;
  background: var(--main-color, #625ff0);
  animation: ewh-progress-slide 1.5s linear infinite;
}

@keyframes ewh-progress-slide {
  from {
    left: -30%;
  }
  to {
    left: 100%;
  }
}

@media (max-width: 900px) {
  .ewh {
    padding: 0 16px;
  }

  .ewh-search span,
  .ewh-search kbd {
    display: none;
  }

  .ewh-search {
    width: 32px;
    justify-content: center;
    padding: 0;
  }
}

@media (max-width: 680px) {
  .ewh-status {
    display: none;
  }
}
</style>
