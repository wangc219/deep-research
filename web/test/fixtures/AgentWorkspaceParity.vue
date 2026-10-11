<script setup>
// 独立验收夹具：复用生产组件和 API，身份及数据由外部测试环境提供。
import { onMounted, ref } from 'vue'
import AgentArtifactsCard from '@/components/AgentArtifactsCard.vue'
import AgentFilePreview from '@/components/AgentFilePreview.vue'
import WorkspaceFileList from '@/components/workspace/WorkspaceFileList.vue'
import { getWorkspaceTree, getWorkspaceFileContent, saveWorkspaceFileContent, downloadWorkspaceFile } from '@/apis/workspace_api'
import { normalizePreviewResponse } from '@/utils/file_preview'
const threadId = 'synthetic-parity-thread-accepted'
const root = '/projects/11111111-1111-4111-8111-111111111111'
const path = ref(root)
const entries = ref([])
const file = ref(null)
const error = ref('')
const saving = ref(false)
const artifacts = ['report.md', 'table.csv', 'chart.svg', 'page.html', 'report.pdf'].map((name) => '/home/gem/user-data' + root + '/outputs/' + name).concat('/home/gem/user-data' + root + '/analyze.py')
async function load(next = path.value) { path.value = next; entries.value = (await getWorkspaceTree(next)).entries }
async function select(entry) {
  error.value = ''
  try {
    if (entry.is_dir) return await load(entry.path)
    const response = await getWorkspaceFileContent(entry.path)
    const data = await normalizePreviewResponse(response, { path: entry.path })
    file.value = { ...data, path: entry.path }
  } catch (cause) { error.value = cause.message }
}
async function save(content) {
  saving.value = true
  try { await saveWorkspaceFileContent(file.value.path, content); file.value = { ...file.value, content }; await load() }
  catch (cause) { error.value = cause.message }
  finally { saving.value = false }
}
async function download(entry) {
  try {
    const response = await downloadWorkspaceFile(entry.path)
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a'); link.href = url; link.download = entry.name + (entry.is_dir ? '.zip' : ''); link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (cause) { error.value = cause.message }
}
onMounted(load)
</script>
<template>
  <main><h1>智能对话沙盒与文件交付 · 合成验收</h1><p>文件由生产 ChatbotAgent 执行图和真实 Docker 沙盒生成，独立 PostgreSQL 保存检查点。</p>
    <AgentArtifactsCard :artifacts="artifacts" :thread-id="threadId" @open-preview="select({ ...$event, path: $event.path.replace('/home/gem/user-data', '') })" />
    <button @click="load(root)">回到任务目录</button>
    <WorkspaceFileList :entries="entries" :current-path="path" @select-entry="select" @select-path="load" @download-entry="download" />
    <p v-if="error" role="alert">{{ error }}</p>
    <AgentFilePreview v-if="file" :file="file" :file-path="file.path" :editable="true" :saving="saving" :show-close="true" :show-fullscreen="true" @close="file = null" @save="save" @download="download({ ...file, name: file.path.split('/').pop() })" />
  </main>
</template>
<style scoped>
main { padding: 30px; max-width: 1300px; margin: auto; color: var(--gray-900); background: var(--gray-0); } h1 { font-size: 24px; } :deep(.agent-file-preview) { min-height: 450px; } button { padding: 8px; margin: 12px 0; } [role='alert'] { color: red; }
</style>
