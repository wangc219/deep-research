<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ArrowLeft, BookOpen, Check, FileSearch, LogOut, Moon, Plus, RefreshCw, Sun, Upload } from '@lucide/vue'
import { useThemeStore } from '@/stores/theme'
import { createDocumentResearchApi, createDocumentTaskMonitor, createDocumentRetrievalPreview, runDocumentTaskOnce, DOCUMENT_TOKEN_KEY, documentTaskKey } from '@/apis/document_research_api'
import EvidenceSources from './document-research/EvidenceSources.vue'
import RetrievalStatus from './document-research/RetrievalStatus.vue'
import ReportPanel from './document-research/ReportPanel.vue'
import ModelSettings from './document-research/ModelSettings.vue'
import DeliveryPanel from './document-research/DeliveryPanel.vue'

const theme = useThemeStore()
const token = ref('')
const user = ref('')
const settingsOpen = ref(false)
const health = ref(null)
const healthError = ref('')
const error = ref('')
const busy = ref('')
const libraries = ref([])
const selected = ref([])
const activeLibrary = ref(null)
const documents = ref([])
const preview = ref(null)
const libraryName = ref('')
const task = ref(null)
const connectionError = ref('')
const runUnconfirmed = ref(false)
const deletion = ref(null)
const fields = reactive({ mode: 'research', allow_web_search: false, problem: '', parser_version: '', expected_result: '', constraints: '', allow_public: false, public_query: '', allow_external_model: false })
const answers = reactive({ parser_version: '', expected_result: '', constraints: '' })
const questionLabels = { parser_version: '当前解析器与版本 / 配置', expected_result: '期望的正确结果', constraints: '资源、时延、成本等约束' }
const statusLabels = { ready: '准备就绪', needs_input: '需要补充信息', running: '正在检索与生成', completed: '报告已生成', failed: '任务失败', cancelled: '任务已取消' }
const isRunning = computed(() => task.value?.status === 'running')
const hasZhipuSelection = computed(() => libraries.value.some((item) => selected.value.includes(item.id) && item.kind === 'zhipu'))
const api = createDocumentResearchApi(() => token.value)
const retrievalResult = ref(null)
const retrievalError = ref('')
const retrievalLoading = ref(false)
const retrievalStopped = ref(false)
const publicQueryInvalid = computed(() => (fields.allow_public || fields.allow_web_search) && (!fields.public_query.trim() || (fields.allow_web_search && fields.public_query.trim().length > 70)))
let alive = true
let taskGeneration = 0
const retrievalPreview = createDocumentRetrievalPreview({
  retrieve: api.retrieve,
  onResult: (result) => { retrievalResult.value = result },
  onError: (cause) => {
    retrievalError.value = cause.message || '检索预览失败，请重试。'
    if ([401, 403].includes(cause.status)) showError(cause)
  },
  onLoading: (value) => { retrievalLoading.value = value }
})
function clearRetrieval() {
  retrievalPreview.stop()
  retrievalResult.value = null
  retrievalError.value = ''
  retrievalStopped.value = false
}
function stopRetrieval() {
  retrievalPreview.stop()
  retrievalStopped.value = true
}
function retrieveEvidence() {
  clearRetrieval()
  void retrievalPreview.start({
    problem: fields.problem, library_ids: [...selected.value], allow_public: fields.allow_public,
    public_query: fields.public_query, allow_web_search: fields.allow_web_search
  })
}
watch(() => [token.value, user.value, JSON.stringify(selected.value), fields.problem, fields.public_query, fields.allow_public, fields.allow_web_search, fields.mode], clearRetrieval, { flush: 'sync' })

function remember(key, value) {
  try { value === null ? sessionStorage.removeItem(key) : sessionStorage.setItem(key, value) } catch { /* 禁用存储时本页仍可使用。 */ }
}
function recalled(key) { try { return sessionStorage.getItem(key) || '' } catch { return '' } }

function acceptTask(next) {
  if (!alive || !user.value) return
  runUnconfirmed.value = false
  task.value = next
  selected.value = [...next.library_ids]
  connectionError.value = ''
  remember(documentTaskKey(user.value), next.id)
  for (const field of Object.keys(answers)) answers[field] = next[field] || ''
}
function showError(cause) {
  error.value = cause.message || '请求失败，请重试。'
  if ([401, 403, 404].includes(cause.status)) {
    invalidateTaskScope()
    monitor.stop()
    clearRetrieval()
    task.value = null
    preview.value = null
    documents.value = []
    if (user.value) remember(documentTaskKey(user.value), null)
    if ([401, 403].includes(cause.status)) {
      libraries.value = []
      selected.value = []
      activeLibrary.value = null
    }
    if (cause.status === 401) {
      user.value = ''
      remember(DOCUMENT_TOKEN_KEY, null)
    }
  }
}
const monitor = createDocumentTaskMonitor({
  readTask: api.task,
  onTask: acceptTask,
  onError: (cause) => {
    if ([401, 403, 404].includes(cause.status)) showError(cause)
    else connectionError.value = `${cause.message} 正在重试获取任务状态；尚未确认任务终态。`
  }
})
function invalidateTaskScope() {
  taskGeneration += 1
  runUnconfirmed.value = false
}
function currentTaskScope(taskId) {
  const generation = taskGeneration
  const identity = user.value
  const credential = token.value
  return () => alive && generation === taskGeneration && !!identity && identity === user.value && credential === token.value && (!taskId || task.value?.id === taskId)
}
watch(() => [token.value, user.value], () => { invalidateTaskScope(); monitor.stop() }, { flush: 'sync' })
async function startKnownTask(taskId, isCurrent = currentTaskScope(taskId)) {
  await runDocumentTaskOnce({
    taskId, runTask: api.runTask, isCurrent, onTask: acceptTask, monitor,
    onPending: (value) => { runUnconfirmed.value = value },
    onError: showError,
    onUnknown: (cause) => { connectionError.value = `${cause.message} 正在确认启动结果；不会重复发送启动请求。` }
  })
}
async function action(label, callback) {
  if (busy.value) return
  busy.value = label
  error.value = ''
  try { await callback() } catch (cause) { if (alive) showError(cause) } finally { busy.value = '' }
}
async function checkHealth() {
  healthError.value = ''
  try { health.value = await api.health() } catch (cause) { health.value = null; healthError.value = cause.message }
}
async function loadLibraries() {
  libraries.value = (await api.libraries()).items
  selected.value = selected.value.filter((id) => libraries.value.some((item) => item.id === id))
}
async function connect() {
  await action('连接服务', async () => {
    const session = await api.session()
    user.value = session.user
    remember(DOCUMENT_TOKEN_KEY, token.value.trim())
    await loadLibraries()
    const taskId = recalled(documentTaskKey(user.value))
    if (taskId) monitor.start(taskId)
  })
}
function disconnect() {
  settingsOpen.value = false
  invalidateTaskScope()
  monitor.stop()
  remember(DOCUMENT_TOKEN_KEY, null)
  token.value = ''; user.value = ''; task.value = null; libraries.value = []; selected.value = []
  documents.value = []; activeLibrary.value = null; preview.value = null; error.value = ''; connectionError.value = ''
  deletion.value = null
  Object.assign(fields, { mode: 'research', allow_web_search: false, problem: '', parser_version: '', expected_result: '', constraints: '', allow_public: false, public_query: '', allow_external_model: false })
}
async function openLibrary(library) {
  await action('加载资料', async () => {
    preview.value = null
    documents.value = []
    activeLibrary.value = library
    if (library.kind === 'local') documents.value = (await api.documents(library.id)).items
  })
}
async function createLibrary() {
  await action('创建资料库', async () => {
    const library = await api.createLibrary(libraryName.value.trim())
    libraryName.value = ''
    await loadLibraries()
    activeLibrary.value = library
    documents.value = []
    preview.value = null
  })
}
async function upload(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  if (file.size > 10 * 1024 * 1024) { error.value = '文件超过 10 MiB，请缩小后上传。'; return }
  await action('上传并解析', async () => {
    clearRetrieval()
    await api.upload(activeLibrary.value.id, file)
    documents.value = (await api.documents(activeLibrary.value.id)).items
    await loadLibraries()
  })
}
async function deleteSelected() {
  await action('删除资料', async () => {
    clearRetrieval()
    const target = deletion.value
    if (target.kind === 'library') {
      await api.deleteLibrary(target.id)
      activeLibrary.value = null; documents.value = []; preview.value = null
    } else {
      await api.deleteDocument(target.id)
      preview.value = null
      documents.value = (await api.documents(activeLibrary.value.id)).items
    }
    deletion.value = null
    await loadLibraries()
    if (task.value) monitor.start(task.value.id)
  })
}
async function createTask() {
  await action(fields.mode === 'answer' ? '生成有据回答' : '创建研究任务', async () => {
    monitor.stop()
    invalidateTaskScope()
    clearRetrieval()
    const payload = { ...fields, library_ids: [...selected.value] }
    if (fields.mode === 'answer') Object.assign(payload, { parser_version: '', expected_result: '', constraints: '' })
    const isCurrent = currentTaskScope()
    const created = await api.createTask(payload)
    if (!isCurrent()) return
    acceptTask(created)
    if (created.mode === 'answer' && created.status === 'ready' && created.allow_external_model) {
      await startKnownTask(created.id)
    }
  })
}
async function supplement(acceptAssumptions) {
  await action('保存补充信息', async () => {
    acceptTask(await api.updateTask(task.value.id, { ...answers, accept_assumptions: acceptAssumptions }))
  })
}
async function runTask() {
  await action('启动研究', async () => {
    const taskId = task.value?.id
    if (!taskId || runUnconfirmed.value) return
    const isCurrent = currentTaskScope(taskId)
    await checkHealth()
    await startKnownTask(taskId, isCurrent)
  })
}
async function cancelTask() {
  await action('取消研究', async () => {
    monitor.stop()
    try {
      acceptTask(await api.cancelTask(task.value.id))
    } finally {
      // 取消请求断线时终态未知，继续读取服务端状态。
      if (isRunning.value) monitor.start(task.value.id)
    }
  })
}
function newTask() {
  invalidateTaskScope()
  monitor.stop()
  remember(documentTaskKey(user.value), null)
  task.value = null; connectionError.value = ''; error.value = ''
}
onMounted(async () => {
  token.value = recalled(DOCUMENT_TOKEN_KEY)
  await checkHealth()
  if (alive && token.value) await connect()
})
onUnmounted(() => { alive = false; invalidateTaskScope(); monitor.stop(); clearRetrieval() })
</script>

<template>
  <main class="document-research">
    <header class="topbar">
      <a href="/knowledge" class="return-link"><ArrowLeft :size="16" />返回原平台</a>
      <div class="topbar-actions">
        <span v-if="user" class="muted">{{ user }}</span>
        <button type="button" class="icon-button" :aria-label="theme.isDark ? '切换浅色' : '切换深色'" @click="theme.toggleTheme"><Sun v-if="theme.isDark" :size="18" /><Moon v-else :size="18" /></button>
        <button v-if="user" type="button" class="quiet" :disabled="!!busy" @click="disconnect"><LogOut :size="15" />断开访问</button>
      </div>
    </header>
    <div class="page-content">
      <div class="intro"><div class="eyebrow"><FileSearch :size="17" />软件研发 / 文档解析</div><h1>让解析方案有据可依</h1><p>先检索资料、核对原文，再获取有来源的回答或制定可验证的研发方案。</p></div>
      <div v-if="healthError" class="notice error" role="alert">{{ healthError }} <button type="button" @click="checkHealth">重新检查</button></div>
      <div v-else-if="health && !health.model_configured" class="notice" role="status">模型尚未配置。资料管理和检索预览可以使用；生成回答或报告前，请管理员连接后打开“模型设置”，填写模型地址、模型名和密钥。<button type="button" @click="checkHealth">重新检查</button></div>
      <div v-if="error" class="notice error" role="alert">{{ error }}</div>

      <form v-if="!user" class="panel connect" @submit.prevent="connect">
        <h2>连接文档研发服务</h2><p class="muted">使用管理员提供的专用访问令牌。只在本标签页会话中保存。</p>
        <label for="document-token">专用访问令牌</label><div class="inline"><input id="document-token" v-model="token" type="password" autocomplete="off" required :disabled="!!busy" placeholder="输入专用令牌" /><button type="submit" class="primary" :disabled="!!busy || !token.trim()">{{ busy || '连接服务' }}</button></div>
        <p class="muted">此入口管理通用文档解析任务与资料。模型密钥可由管理员在此页的“模型设置”中配置；智谱检索密钥及库授权仍由服务端管理。</p>
      </form>

      <div v-else class="workspace">
        <aside class="panel library-panel" aria-label="任务资料范围">
          <div class="section-heading"><h2><BookOpen :size="18" />任务资料</h2><button class="icon-button" type="button" :disabled="!!busy" aria-label="刷新资料库" @click="action('刷新资料库', loadLibraries)"><RefreshCw :size="16" /></button></div>
          <p class="muted">勾选本次研究可检索的库。未勾选的库不会被读取。</p>
          <div v-if="!libraries.length" class="empty">还没有资料库。创建一个本地库，上传需求或失败样本。</div>
          <div v-for="library in libraries" :key="library.id" class="library-row" :class="{ selected: activeLibrary?.id === library.id }">
            <input :id="`library-${library.id}`" v-model="selected" type="checkbox" :value="library.id" :disabled="!!task || !!busy" :aria-label="`选择资料库 ${library.name}`" />
            <button class="library-open" type="button" :disabled="!!busy" @click="openLibrary(library)"><strong>{{ library.name }}</strong><span>{{ library.kind === 'zhipu' ? `智谱 · 只读 · ${library.document_count == null ? '文档数量未知' : library.document_count + ' 份资料'}` : `本地 · ${library.document_count} 份资料` }}</span></button>
          </div>
          <form class="new-library" @submit.prevent="createLibrary"><label for="library-name">新建本地资料库</label><div class="inline"><input id="library-name" v-model="libraryName" maxlength="100" placeholder="例如：复杂表格失败样本" required :disabled="!!busy" /><button type="submit" class="icon-button" :disabled="!!busy || !libraryName.trim()" aria-label="创建资料库"><Plus :size="19" /></button></div></form>
          <p class="muted small">智谱已有知识库由管理员授权后列于上方。这里仅检索，不上传、同步或删除智谱文档。</p>

          <section v-if="activeLibrary" class="documents">
            <h3>{{ activeLibrary.name }}</h3>
            <template v-if="activeLibrary.kind === 'local'">
              <label class="upload" :class="{ disabled: busy }"><Upload :size="16" />{{ busy === '上传并解析' ? '上传并解析中…' : '上传需求 / 失败样本' }}<input type="file" accept=".pdf,.docx,.txt,.md" :disabled="!!busy" aria-label="上传资料" @change="upload" /></label>
              <p class="muted small">PDF、DOCX、TXT、MD，每份 ≤ 10 MiB。仅预览提取文本，复杂表格不保证保真；扫描 PDF 暂不支持 OCR。</p>
              <p v-if="!documents.length" class="empty">此库暂无文档。</p>
              <div v-for="doc in documents" :key="doc.id" class="document-row"><button type="button" class="text-button" :disabled="!!busy" @click="action('预览文档', async () => { preview = await api.document(doc.id) })">{{ doc.name }}</button><span class="small" :class="{ 'error-text': doc.status === 'failed' }">{{ doc.status === 'ready' ? `${doc.chunk_count} 个片段` : `解析失败：${doc.error || '无可用文本'}` }}</span><button type="button" class="text-button danger" :disabled="!!busy" @click="deletion = { kind: 'document', id: doc.id, name: doc.name }">删除</button></div>
              <button type="button" class="text-button danger" :disabled="!!busy" @click="deletion = { kind: 'library', id: activeLibrary.id, name: activeLibrary.name }">删除此资料库</button>
            </template>
            <p v-else class="muted">本次检索得到的文档片段及引用，可在检索预览中查看；生成后会列于“本次提供给模型的来源”。</p>
          </section>
          <div v-if="deletion" class="notice" role="alert"><p>删除“{{ deletion.name }}”？已有任务可能因此失去相关证据。</p><div class="inline"><button type="button" :disabled="!!busy" @click="deleteSelected">确认删除</button><button type="button" :disabled="!!busy" @click="deletion = null">保留</button></div></div>
          <section v-if="preview" class="preview"><div class="section-heading"><h3>{{ preview.name }} · 提取文本</h3><button type="button" class="text-button" @click="preview = null">关闭预览</button></div><p v-if="!preview.chunks?.length">暂无可预览文本。</p><div v-for="chunk in preview.chunks" :key="chunk.id"><span class="muted small">{{ chunk.page === null || chunk.page === undefined ? '未提供页码' : `第 ${chunk.page} 页` }}</span><pre>{{ chunk.text }}</pre></div></section>
        </aside>

        <div class="research-main">
          <button type="button" class="quiet" @click="settingsOpen = !settingsOpen">{{ settingsOpen ? '关闭模型设置' : '模型设置' }}</button>
          <ModelSettings v-if="settingsOpen" :key="user + token" :api="api" @saved="checkHealth" />
          <form v-if="!task" class="panel research-form" @submit.prevent="createTask">
            <div class="section-heading"><h2>{{ fields.mode === 'answer' ? '基于资料提问' : '定义研究问题' }}</h2><span class="badge">已选 {{ selected.length }} 个库</span></div>
            <div class="mode-switch" role="group" aria-label="工作模式"><button type="button" :aria-pressed="fields.mode === 'answer'" @click="fields.mode = 'answer'">证据问答</button><button type="button" :aria-pressed="fields.mode === 'research'" @click="fields.mode = 'research'">深研方案</button></div>
            <p class="muted small">{{ fields.mode === 'answer' ? '每个问题都会重新检索已选资料，回答逐条附原文；暂不自动带入上一个问题的对话历史。' : '比较方案、制定实验步骤与验收指标；缺失条件会先向你确认。' }}</p>
            <label for="research-problem">{{ fields.mode === 'answer' ? '想了解的问题' : '需求与当前瓶颈' }}</label><textarea id="research-problem" v-model="fields.problem" rows="4" required maxlength="8000" placeholder="例如：跨页表格与合并单元格识别不准。请结合已上传需求、失败样本，比较 Docling、PaddleOCR、Unstructured，给出实验步骤与验收指标。" />
            <div v-if="fields.mode === 'research'" class="supplement-fields"><label v-for="(label, field) in questionLabels" :key="field" :for="`research-${field}`">{{ label }}<textarea :id="`research-${field}`" v-model="fields[field]" rows="2" maxlength="4000" placeholder="可以暂时留空；创建后最多补充 3 个问题。" /></label></div>
            <fieldset><legend>证据与数据发送范围</legend>
              <label class="check-label"><input v-model="fields.allow_public" type="checkbox" />补充官方项目资料</label><p class="muted small">读取 Docling、PaddleOCR、Unstructured 的官方 README，并在本地选取片段；不向这些站点发送问题或文档。</p>
              <label class="check-label"><input v-model="fields.allow_web_search" type="checkbox" />启用公开网络检索</label><p class="muted small">仅将你下方明确填写的公开检索词发送给智谱搜索服务。搜索摘要不等于已核实的完整原文；私人问题和文档不会作为公开搜索词发送。</p>
              <label v-if="fields.allow_public || fields.allow_web_search" for="public-query">公开检索词<input id="public-query" v-model="fields.public_query" :maxlength="fields.allow_web_search ? 70 : 500" :placeholder="fields.allow_web_search ? 'site:docling-project.github.io/docling table' : '例如：document parsing complex tables'" required /><span class="small muted">{{ fields.allow_web_search ? `将发送给搜索服务（${fields.public_query.length}/70 字符）。` : '仅在本地选择官方项目片段。' }}请勿填写客户名、内部项目名或文档内容。</span></label>
              <p v-if="fields.allow_web_search" class="muted small">建议限定官方站点，例如 site:docling-project.github.io/docling table；无匹配时请调整关键词或补充官方项目资料。</p>
              <p v-if="hasZhipuSelection" class="notice">已选择智谱库：预览检索或启动任务时，问题会发送给智谱用于检索；不会上传原文件。</p>
              <label class="check-label"><input v-model="fields.allow_external_model" type="checkbox" />我同意将研究问题、补充信息和选中资料的检索片段发送给管理员配置的外部模型。</label>
            </fieldset>
            <section class="retrieval-preview" aria-label="检索预览">
              <div class="inline wrap"><button type="button" :disabled="!!busy || retrievalLoading || !fields.problem.trim() || publicQueryInvalid" @click="retrieveEvidence">预览检索结果</button><button v-if="retrievalLoading" type="button" @click="stopRetrieval">停止等待</button><span class="muted small">只检索，不调用生成模型，也不需要勾选外部模型同意。</span></div>
              <p v-if="retrievalLoading" role="status">正在检索选定资料，请稍候…</p>
              <p v-if="retrievalStopped" role="status">已停止本页等待；远端检索可能已执行，未确认远端取消。</p>
              <p v-if="retrievalError" class="notice error" role="alert">{{ retrievalError }}</p>
              <div v-if="retrievalResult" class="retrieval-results">
                <h3>检索结果 · {{ retrievalResult.sources.length }} 个片段</h3>
                <RetrievalStatus :items="retrievalResult.retrieval_status || []" />
                <div v-if="retrievalResult.warnings?.length" class="notice"><ul><li v-for="(warning, i) in retrievalResult.warnings" :key="i">{{ warning }}</li></ul></div>
                <p v-if="!retrievalResult.sources.length" class="empty">未找到可用片段。可以调整问题或选择其他资料库；这不表示资料库没有文档。</p>
                <EvidenceSources :sources="retrievalResult.sources" prefix="preview-source" />
                <p class="muted small">这是当前检索结果。生成回答或方案时会重新检索，结果可能发生变化。</p>
              </div>
            </section>
            <div class="form-footer"><span class="muted small">{{ fields.mode === 'answer' ? '回答只陈述可引用证据；缺少资料会明确提示。' : '输出为研究建议；性能与验收结果需实际实验验证。' }}</span><button type="submit" class="primary" :disabled="!!busy || retrievalLoading || !fields.problem.trim() || publicQueryInvalid || (fields.mode === 'answer' && (!health?.model_configured || !fields.allow_external_model))">{{ busy || (fields.mode === 'answer' ? '获取有据回答' : '创建研究任务') }}</button></div>
          </form>

          <section v-else class="panel task-panel" aria-label="研究任务">
            <div class="section-heading"><h2>{{ statusLabels[task.status] || task.status }}</h2><button v-if="!isRunning" type="button" class="quiet" :disabled="!!busy" @click="newTask"><Plus :size="15" />新问题 / 研究</button></div>
            <p class="task-problem">{{ task.problem }}</p><p class="muted small">{{ task.mode === 'answer' ? '证据问答' : '深研方案' }} · 任务 {{ task.id }} · 资料范围已固定；新问题可重新选库。</p>
            <div v-if="connectionError" class="notice error" role="alert">{{ connectionError }}<button type="button" @click="monitor.start(task.id)">立即重试</button></div>
            <div v-if="task.status === 'needs_input'" class="questions"><h3>开始前，补充几个关键信息</h3><label v-for="question in task.questions.slice(0, 3)" :key="question.field" :for="`answer-${question.field}`">{{ question.question }}<textarea :id="`answer-${question.field}`" v-model="answers[question.field]" rows="2" maxlength="4000" /></label><div class="inline wrap"><button type="button" class="primary" :disabled="!!busy" @click="supplement(false)">保存补充信息</button><button type="button" :disabled="!!busy" @click="supplement(true)">接受剩余未知项为假设</button></div><p class="muted small">未知项会在报告中标注，并给出验证建议。</p></div>
            <div v-if="task.assumptions?.length" class="notice"><strong>本次假设</strong><ul><li v-for="(assumption, i) in task.assumptions" :key="i">{{ assumption }}</li></ul></div>
            <div v-if="task.status === 'ready'" class="run-ready"><p>将检索选定资料并{{ task.mode === 'answer' ? '生成有据回答' : '整理研究方案' }}。{{ task.allow_web_search ? '已允许公开网络检索。' : task.allow_public ? '已允许补充官方项目资料。' : '仅使用选定资料。' }}</p><p v-if="!task.allow_external_model" class="notice">此任务未同意外部模型数据发送。请新建研究并确认发送范围后再启动。</p><button type="button" class="primary" :disabled="!!busy || runUnconfirmed || !health?.model_configured || !task.allow_external_model" @click="runTask">{{ runUnconfirmed ? '正在确认启动结果' : busy || (task.mode === 'answer' ? '开始问答' : '开始研究') }}</button></div>
            <div v-if="isRunning" class="running" role="status"><span class="pulse" /><div><strong>{{ task.mode === 'answer' ? '正在检索与生成回答' : '正在检索与生成方案' }}</strong><p>每隔约 1.5 秒读取真实任务状态。可离开此页面，返回后继续查看。</p></div><button type="button" :disabled="!!busy" @click="cancelTask">取消研究</button></div>
            <div v-if="task.status === 'cancelled'" class="notice">已取消本地等待与结果输出。远端模型请求或费用可能已经发生。</div>
            <div v-if="task.status === 'failed'" class="notice error" role="alert">{{ task.error || '任务未完成，请检查服务配置或证据后新建研究。' }}</div>
            <div v-if="task.status === 'completed' && !task.report" class="notice error">任务标记完成，但未返回报告。请检查服务日志。</div>
            <ReportPanel v-if="task.status === 'completed' && task.report" :report="task.report" />
            <DeliveryPanel v-if="task.status === 'completed' && task.report" :key="task.id + user + token" :api="api" :task-id="task.id" />
          </section>
          <div v-if="!task" class="workflow"><span><Check :size="15" />来源可追溯</span><span><Check :size="15" />事实与推断分开</span><span><Check :size="15" />未实测结果明确标注</span></div>
        </div>
      </div>
      <p v-if="busy && user" class="busy-indicator" role="status">{{ busy }}…</p>
    </div>
  </main>
</template>

<style scoped>
.document-research { min-height: 100dvh; height: 100%; overflow-y: auto; background: var(--gray-25); color: var(--gray-900); font-size: 14px; line-height: 1.6; }
.topbar { min-height: 62px; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 32px; border-bottom: 1px solid var(--gray-200); background: var(--gray-0); }
.topbar-actions, .return-link, .eyebrow, .section-heading, h2, .inline, .workflow, .workflow span { display: flex; align-items: center; gap: 10px; }
.return-link { color: var(--gray-700); text-decoration: none; } .return-link:hover { color: var(--main-color); }
.page-content { max-width: 1320px; margin: 0 auto; padding: 32px; } .intro { margin-bottom: 26px; } .eyebrow { color: var(--main-color); font-size: 13px; font-weight: 600; letter-spacing: .04em; }
h1 { font-size: clamp(25px, 3vw, 32px); margin: 7px 0; font-weight: 650; letter-spacing: -.025em; } h2 { font-size: 18px; font-weight: 600; margin: 0; } h3 { font-size: 15px; font-weight: 600; margin: 0 0 12px; } p { margin: 8px 0 14px; } .intro p { color: var(--gray-600); margin-bottom: 0; }
.workspace { display: grid; grid-template-columns: 310px minmax(0, 1fr); gap: 24px; align-items: start; } .research-main { min-width: 0; } .panel { border: 1px solid var(--gray-200); background: var(--gray-0); border-radius: 14px; padding: 24px; box-shadow: 0 2px 4px var(--shadow-0); }
.connect { max-width: 650px; } .library-panel { padding: 20px; } .section-heading { justify-content: space-between; margin-bottom: 16px; gap: 8px; }
.muted { color: var(--gray-600); } .small { font-size: 12px; } label { display: block; font-weight: 500; margin-bottom: 8px; } input:not([type='checkbox'], [type='file']), textarea { display: block; width: 100%; min-width: 0; border: 1px solid var(--gray-300); border-radius: 8px; background: var(--gray-0); color: var(--gray-900); padding: 10px 12px; font: inherit; }
textarea { resize: vertical; margin-top: 6px; } input::placeholder, textarea::placeholder { color: var(--gray-500); } input:focus, textarea:focus { outline: 2px solid var(--main-200); border-color: var(--main-color); }
input[type='checkbox'] { width: 17px; height: 17px; accent-color: var(--main-color); flex-shrink: 0; } button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 9px 14px; border: 1px solid var(--gray-300); border-radius: 8px; color: var(--gray-800); background: var(--gray-0); font: inherit; cursor: pointer; }
button:hover:not(:disabled) { background: var(--gray-50); } button:disabled { opacity: .5; cursor: not-allowed; } button:focus-visible, a:focus-visible, summary:focus-visible { outline: 2px solid var(--main-color); outline-offset: 3px; } .primary { background: var(--main-color); border-color: var(--main-color); color: white; white-space: nowrap; } .primary:hover:not(:disabled) { background: var(--main-700); }
.icon-button { padding: 8px; } .quiet { padding: 6px 9px; border-color: transparent; } .inline input { flex: 1; } .inline.wrap { flex-wrap: wrap; } .text-button { padding: 2px 0; border: 0; background: none; justify-content: flex-start; text-align: left; color: var(--main-color); overflow-wrap: anywhere; } .danger, .error-text { color: var(--color-error-700); }
.library-row { display: flex; align-items: center; gap: 9px; padding: 10px; border-radius: 8px; border: 1px solid transparent; margin: 4px -8px; } .library-row.selected { background: var(--main-20); border-color: var(--main-200); }
.library-open { display: flex; align-items: flex-start; flex: 1; min-width: 0; gap: 1px; flex-direction: column; padding: 0; border: 0; background: none; text-align: left; } .library-open strong { overflow-wrap: anywhere; font-weight: 500; } .library-open span { color: var(--gray-600); font-size: 12px; }
.new-library { border-top: 1px solid var(--gray-200); margin-top: 18px; padding-top: 18px; } .empty { color: var(--gray-600); border: 1px dashed var(--gray-300); border-radius: 8px; padding: 16px; font-size: 13px; }
.documents, .preview { margin-top: 22px; border-top: 1px solid var(--gray-200); padding-top: 18px; } .documents h3, .preview h3 { overflow-wrap: anywhere; } .upload { display: flex; align-items: center; justify-content: center; gap: 7px; padding: 11px 8px; color: var(--main-color); background: var(--main-20); border: 1px dashed var(--main-200); border-radius: 8px; cursor: pointer; position: relative; } .upload:focus-within { outline: 2px solid var(--main-color); } .upload input { position: absolute; width: 100%; height: 100%; opacity: 0; cursor: pointer; } .upload.disabled { opacity: .5; }
.document-row { display: flex; align-items: flex-start; flex-direction: column; margin: 14px 0; gap: 4px; } .document-row > .small { overflow-wrap: anywhere; } pre { font: inherit; font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; padding: 10px; background: var(--gray-50); max-height: 240px; overflow-y: auto; }
.mode-switch { display: flex; gap: 8px; margin-bottom: 12px; } .mode-switch button { flex: 1; } .mode-switch button[aria-pressed='true'] { border-color: var(--main-color); background: var(--main-20); color: var(--main-800); } .retrieval-preview { margin: 20px 0; padding-top: 18px; border-top: 1px solid var(--gray-200); } .retrieval-results { margin-top: 18px; }
.supplement-fields { margin-top: 20px; display: grid; gap: 12px; } fieldset { border: 1px solid var(--gray-200); padding: 16px; border-radius: 10px; margin: 20px 0; } legend { font-size: 13px; font-weight: 600; width: auto; padding: 0 6px; } .check-label { display: flex; align-items: flex-start; gap: 9px; font-weight: 400; } .check-label input { margin-top: 3px; }
.badge { background: var(--main-50); color: var(--main-800); font-size: 12px; border-radius: 5px; padding: 3px 8px; white-space: nowrap; } .notice { padding: 14px 16px; border: 1px solid var(--main-200); background: var(--main-20); color: var(--gray-800); border-radius: 9px; margin-bottom: 18px; overflow-wrap: anywhere; } .notice button { margin-left: 5px; padding: 4px 8px; font-size: 12px; } .notice.error { border-color: var(--color-error-100); background: var(--gray-0); color: var(--color-error-700); }
.form-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; } .workflow { flex-wrap: wrap; justify-content: center; color: var(--gray-600); margin-top: 20px; font-size: 12px; gap: 18px; } .workflow span { gap: 5px; }
.questions { padding: 20px 0; } .questions label { margin-bottom: 18px; } .task-problem { white-space: pre-wrap; overflow-wrap: anywhere; } .run-ready { padding-top: 14px; } .running { display: flex; align-items: center; gap: 14px; border: 1px solid var(--main-200); border-radius: 9px; padding: 18px; margin-top: 22px; } .running > div { flex: 1; } .running p { margin: 4px 0 0; font-size: 13px; color: var(--gray-600); } .pulse { height: 10px; width: 10px; flex-shrink: 0; background: var(--main-color); border-radius: 50%; animation: pulse 1.5s ease infinite; } .busy-indicator { position: fixed; bottom: 15px; left: 50%; transform: translateX(-50%); padding: 8px 18px; background: var(--gray-900); color: var(--gray-0); border-radius: 20px; box-shadow: 0 2px 8px var(--shadow-2); }
@keyframes pulse { 50% { opacity: .4; } } @media (prefers-reduced-motion: reduce) { .pulse { animation: none; } }
@media (max-width: 850px) { .workspace { grid-template-columns: 1fr; } .page-content { padding: 22px 16px; } .topbar { padding: 10px 16px; } .form-footer, .running { align-items: flex-start; flex-wrap: wrap; } .panel { padding: 20px; } }
@media (max-width: 440px) { .topbar-actions { gap: 3px; } .topbar-actions > .muted { display: none; } .panel { padding: 16px; } .connect .inline { flex-wrap: wrap; } .connect .inline input { flex-basis: 100%; } .form-footer > button { width: 100%; } }
</style>
