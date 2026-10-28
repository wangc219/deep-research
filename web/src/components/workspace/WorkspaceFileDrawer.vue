<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ExternalLink, RefreshCw } from '@lucide/vue'
import AgentFilePreview from '@/components/AgentFilePreview.vue'
import { getWorkspaceFileContent } from '@/apis/workspace_api'
import { normalizePreviewResponse } from '@/utils/file_preview'

const props = defineProps({ path: { type: String, default: '' } })
const emit = defineEmits(['close'])
const router = useRouter()
const file = ref(null)
const loading = ref(false)
const error = ref('')
let requestId = 0
const revoke = () => {
  if (file.value?.previewUrl) URL.revokeObjectURL(file.value.previewUrl)
  file.value = null
}
async function load() {
  const id = ++requestId
  const path = props.path
  revoke()
  error.value = ''
  loading.value = !!path
  if (!path) return
  try {
    const response = await getWorkspaceFileContent(path)
    if (id !== requestId) return
    const result = await normalizePreviewResponse(response, { path, name: path.split('/').pop() })
    if (id !== requestId) {
      if (result.previewUrl) URL.revokeObjectURL(result.previewUrl)
      return
    }
    file.value = result
  } catch (cause) {
    if (id === requestId) error.value = cause.message || '文件预览失败，请重试'
  } finally {
    if (id === requestId) loading.value = false
  }
}
function close() {
  requestId++
  revoke()
  emit('close')
}
function openWorkspace() {
  router.push({ path: '/workspace', query: { open: props.path } })
  close()
}
watch(() => props.path, load, { immediate: true })
onBeforeUnmount(() => {
  requestId++
  revoke()
})
</script>

<template>
  <a-drawer
    :open="!!path"
    title="沙盒文件预览"
    placement="right"
    width="min(860px, 100vw)"
    :body-style="{ padding: '0', display: 'flex', flexDirection: 'column', minHeight: '0' }"
    @close="close"
  >
    <template #extra
      ><a-button class="workspace-drawer-open" size="small" @click="openWorkspace"
        ><ExternalLink :size="14" />打开完整工作区</a-button
      ></template
    >
    <p class="workspace-drawer-path" :title="path">{{ path }}</p>
    <div v-if="loading" class="workspace-drawer-state" role="status">
      <a-spin />
      <p>正在加载沙盒文件…</p>
    </div>
    <div v-else-if="error" class="workspace-drawer-state" role="alert">
      <p>{{ error }}</p>
      <a-button class="workspace-drawer-open" @click="load"
        ><RefreshCw :size="14" />重新加载</a-button
      >
    </div>
    <AgentFilePreview
      v-else-if="file"
      :file="file"
      :file-path="path"
      :show-download="false"
      :show-close="false"
      :show-fullscreen="true"
      :full-height="true"
      :editable="false"
      container-class="workspace-drawer-preview"
    />
  </a-drawer>
</template>

<style scoped>
.workspace-drawer-open {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.workspace-drawer-path {
  margin: 0;
  padding: 12px 20px;
  font-size: 12px;
  color: var(--gray-600);
  background: var(--gray-50);
  border-bottom: 1px solid var(--gray-200);
  overflow-wrap: anywhere;
}
.workspace-drawer-state {
  display: flex;
  flex: 1;
  min-height: 240px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 12px;
  padding: 24px;
  color: var(--gray-600);
}
:deep(.workspace-drawer-preview) {
  flex: 1;
  min-height: 0;
  border-radius: 0;
}
</style>
