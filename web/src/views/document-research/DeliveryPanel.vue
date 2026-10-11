<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import AgentFilePreview from '@/components/AgentFilePreview.vue'
const props = defineProps({ api: { type: Object, required: true }, taskId: { type: String, required: true } })
const items = ref([])
const file = ref(null)
const loading = ref(true)
const busy = ref(false)
const error = ref('')
let alive = true
onUnmounted(() => { alive = false })
async function action(callback) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await callback() } catch (cause) { if (alive) { error.value = cause.message; if ([401, 403, 404].includes(cause.status)) { file.value = null; items.value = [] } } }
  finally { if (alive) busy.value = false }
}
onMounted(async () => {
  await action(async () => { const data = await props.api.artifacts(props.taskId); if (alive) items.value = data.items })
  if (alive) loading.value = false
})
async function open(item) {
  await action(async () => {
    const data = await props.api.artifact(props.taskId, item.name)
    if (alive) file.value = { ...data, previewType: item.name.endsWith('.md') ? 'markdown' : 'text' }
  })
}
async function save(content) {
  const current = file.value
  await action(async () => {
    const data = await props.api.saveArtifact(props.taskId, current.name, { content, expected_sha256: current.sha256 })
    if (alive) { file.value = { ...current, ...data }; const item = items.value.find((item) => item.name === current.name); if (item) item.size = new TextEncoder().encode(content).length }
  })
}
async function download(name) {
  await action(async () => {
    const blob = name ? await props.api.downloadArtifact(props.taskId, name) : await props.api.downloadBundle(props.taskId)
    if (!alive) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = name || 'document-research.zip'; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  })
}
</script>
<template>
  <section class="deliveries" aria-label="研究文件交付">
    <div class="heading"><h3>研究文件交付</h3><button :disabled="busy || loading || !items.length" @click="download()">打包下载 ZIP</button></div>
    <p>报告、网页、证据表及结构化数据均可下载。Markdown 可在线编辑保存；编辑不会改变原始报告，其他格式保留原始版本。</p>
    <p v-if="loading" role="status">正在准备文件…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <div class="cards"><div v-for="item in items" :key="item.name" class="card"><strong>{{ item.name }}</strong><span>{{ (item.size / 1024).toFixed(1) }} KB · {{ item.media_type }}</span><div><button :disabled="busy" @click="open(item)">预览{{ item.editable ? ' / 编辑' : '' }}</button><button :disabled="busy" @click="download(item.name)">下载</button></div></div></div>
    <AgentFilePreview v-if="file" :file="file" :file-path="file.name" :editable="file.name === 'report.md'" :saving="busy" :show-close="!busy" :show-download="!busy" :show-fullscreen="true" @close="file = null" @save="save" @download="download(file.name)" />
  </section>
</template>
<style scoped>
.deliveries { margin-top: 28px; padding-top: 20px; border-top: 1px solid var(--gray-200); } .heading { display: flex; justify-content: space-between; gap: 10px; align-items: center; flex-wrap: wrap; } h3 { margin: 0; } p, span { color: var(--gray-600); } .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin: 18px 0; } .card { padding: 16px; border: 1px solid var(--gray-200); border-radius: 10px; display: flex; flex-direction: column; gap: 8px; } .card span { font-size: 12px; } button { padding: 7px 10px; margin-right: 5px; border: 1px solid var(--gray-300); background: var(--gray-0); color: var(--gray-900); border-radius: 6px; cursor: pointer; } button:disabled { opacity: .5; } [role='alert'] { color: var(--color-error-700); } :deep(.agent-file-preview) { min-height: 420px; border: 1px solid var(--gray-200); }
</style>
