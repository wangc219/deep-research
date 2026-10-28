<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Archive, Download, FolderOpen, RefreshCw, Upload } from '@lucide/vue'
import { message } from 'ant-design-vue'
import { collectionArtifactApi } from '@/apis/collection_artifact_api'
import { databaseApi, documentApi, fileApi } from '@/apis/knowledge_api'
import { importWorkspaceSelection } from '@/utils/workspaceImport'
import { useTaskerStore } from '@/stores/tasker'
import WorkspaceFileDrawer from '@/components/workspace/WorkspaceFileDrawer.vue'

const props = defineProps({ source: { type: String, required: true } })
const emit = defineEmits(['count'])
const previewPath = ref('')
const tasker = useTaskerStore()
const items = ref([])
const selected = ref([])
const errors = ref([])
const error = ref('')
const root = ref('')
const loading = ref(false)
const downloading = ref(false)
const importing = ref(false)
const importOpen = ref(false)
const libraries = ref([])
const kb = ref()
const failures = ref([])
const staged = new Map()
let timer
let disposed = false
const ready = computed(() => items.value.filter((item) => item.available))
const chosen = computed(() => items.value.filter((item) => selected.value.includes(item.id)))
const importable = computed(() => chosen.value.filter((item) => item.import_available))
const busy = computed(() => importing.value || downloading.value)
const title = computed(() =>
  props.source === 'wechat-articles' ? '公众号文章成果' : '视频文字稿成果'
)

async function refresh(sync = false) {
  if (loading.value) return
  loading.value = true
  try {
    const result = await (sync
      ? collectionArtifactApi.sync(props.source)
      : collectionArtifactApi.list(props.source))
    if (disposed) return
    items.value = result.items || []
    errors.value = result.errors || []
    root.value = result.workspace_root
    selected.value = selected.value.filter((id) =>
      items.value.some((item) => item.id === id && item.available)
    )
    error.value = ''
    emit('count', ready.value.length)
  } catch (cause) {
    if (!disposed) error.value = cause.message || '成果加载失败，请重试'
  } finally {
    loading.value = false
  }
}
function schedule() {
  timer = setTimeout(async () => {
    await refresh()
    if (!disposed) schedule()
  }, 5000)
}
function toggle(id, checked) {
  if (checked && selected.value.length >= 100) {
    message.info('每批最多选择 100 项')
    return
  }
  selected.value = checked
    ? [...new Set([...selected.value, id])]
    : selected.value.filter((value) => value !== id)
}
async function download() {
  if (!selected.value.length || busy.value) return
  downloading.value = true
  error.value = ''
  try {
    const blob = await collectionArtifactApi.archive(props.source, [...selected.value])
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${title.value}.zip`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (cause) {
    error.value = cause.message || '批量下载失败'
  } finally {
    downloading.value = false
  }
}
async function openImport() {
  if (!importable.value.length || busy.value) return
  try {
    const result = await databaseApi.getDatabases()
    libraries.value = (result.databases || [])
      .filter((db) => db.can_manage && (db.kb_type || 'milvus') === 'milvus')
      .map((db) => ({ value: db.kb_id, label: db.name }))
    if (!libraries.value.some((item) => item.value === kb.value)) kb.value = undefined
    failures.value = []
    importOpen.value = true
  } catch (cause) {
    error.value = cause.message || '知识库列表加载失败'
  }
}
async function submitImport() {
  if (importing.value || !libraries.value.some((item) => item.value === kb.value)) return
  importing.value = true
  const kbId = kb.value
  const register = tasker.createTaskRegistration()
  try {
    const result = await importWorkspaceSelection({
      kbId,
      paths: importable.value.map((item) => item.import_path),
      staged,
      upload: fileApi.importWorkspaceFiles,
      submit: documentApi.addDocuments,
      onSubmitted: (task) =>
        register({
          ...task,
          name: `${title.value}入库`,
          task_type: 'knowledge_ingest',
          payload: { kb_id: kbId }
        })
    })
    const succeeded = new Set(
      items.value
        .filter((item) => result.succeeded.includes(item.import_path))
        .map((item) => item.id)
    )
    selected.value = selected.value.filter((id) => !succeeded.has(id))
    failures.value = result.failed
    if (result.succeeded.length)
      message.success(`${result.succeeded.length} 项已提交入库，解析与索引进度可在任务中心查看`)
    if (!result.failed.length) importOpen.value = false
  } finally {
    importing.value = false
  }
}
onMounted(async () => {
  await refresh(true)
  if (!disposed) schedule()
})
onBeforeUnmount(() => {
  disposed = true
  clearTimeout(timer)
})
</script>

<template>
  <section class="collection-panel" :aria-label="title">
    <header class="collection-heading">
      <Archive :size="21" />
      <div>
        <h3>{{ title }}</h3>
        <p>下载或转录完成后自动保存到个人沙盒工作区。预览确认后，选择需要的成果入库。</p>
      </div>
      <a-button :loading="loading" :disabled="busy" @click="refresh(true)"
        ><RefreshCw :size="15" />刷新成果</a-button
      >
    </header>
    <p v-if="root" class="collection-path"><FolderOpen :size="15" />个人空间 {{ root }}</p>
    <a-alert v-if="error" type="error" :message="error" show-icon />
    <a-alert
      v-if="errors.length"
      type="warning"
      message="部分成果尚未保存到工作区，可刷新重试"
      show-icon
      ><template #description
        ><div v-for="(failure, i) in errors" :key="i">
          {{ failure.title }}：{{ failure.error }}
        </div></template
      ></a-alert
    >
    <div class="collection-toolbar">
      <a-checkbox
        :disabled="busy || !ready.length"
        :checked="!!ready.length && selected.length === Math.min(ready.length, 100)"
        :indeterminate="!!selected.length && selected.length < Math.min(ready.length, 100)"
        @change="selected = $event.target.checked ? ready.slice(0, 100).map((item) => item.id) : []"
        >选择本批（最多 100 项）</a-checkbox
      >
      <span>已选 {{ selected.length }} / {{ ready.length }}</span>
      <a-button :disabled="!selected.length || importing" :loading="downloading" @click="download"
        ><Download :size="15" />下载所选成果</a-button
      >
      <a-button type="primary" :disabled="!importable.length || busy" @click="openImport"
        ><Upload :size="15" />选择知识库入库</a-button
      >
    </div>
    <a-spin :spinning="loading && !items.length">
      <a-empty v-if="!items.length" description="暂无成果，请先批量选择文章下载或视频转录" />
      <div v-for="item in items" :key="item.id" class="collection-row">
        <a-checkbox
          :checked="selected.includes(item.id)"
          :disabled="busy || !item.available"
          :aria-label="`选择成果：${item.title}`"
          @change="toggle(item.id, $event.target.checked)"
        />
        <div class="collection-copy">
          <strong :title="item.title">{{ item.title }}</strong
          ><small
            >{{ item.account || title }} ·
            {{ item.available ? '已保存到沙盒工作区' : '工作区文件缺失，请刷新恢复' }}</small
          >
        </div>
        <a-button size="small" :disabled="!item.available" @click="previewPath = item.primary_path"
          >侧开预览</a-button
        >
      </div>
    </a-spin>
    <WorkspaceFileDrawer :path="previewPath" @close="previewPath = ''" />
    <a-modal
      :open="importOpen"
      title="选择知识库入库"
      :confirm-loading="importing"
      :closable="!importing"
      :mask-closable="!importing"
      :cancel-button-props="{ disabled: importing }"
      :ok-button-props="{ disabled: !kb || !importable.length }"
      ok-text="提交入库"
      @cancel="importOpen = false"
      @ok="submitImport"
    >
      <p>
        将所选
        {{ importable.length }} 项成果导入目标知识库，自动解析并建立索引。原文件保留在个人工作区。
      </p>
      <a-select
        v-model:value="kb"
        :options="libraries"
        :disabled="importing"
        :placeholder="libraries.length ? '选择目标知识库' : '暂无可管理的知识库'"
        aria-label="成果目标知识库"
        style="width: 100%"
      />
      <a-alert
        v-if="failures.length"
        type="error"
        message="以下文件未提交，可保留选择后重试"
        show-icon
        style="margin-top: 16px"
        ><template #description
          ><p v-for="failure in failures" :key="failure.path">
            {{ failure.path.split('/').pop() }}：{{ failure.error }}
          </p></template
        ></a-alert
      >
    </a-modal>
  </section>
</template>

<style scoped>
.collection-panel {
  padding: 22px;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--gray-0);
  color: var(--gray-800);
}
.collection-heading,
.collection-toolbar,
.collection-row,
.collection-path {
  display: flex;
  align-items: center;
  gap: 12px;
}
.collection-heading > svg {
  color: var(--main-color);
  flex-shrink: 0;
}
.collection-heading > div {
  flex: 1;
}
.collection-heading h3 {
  margin: 0 0 6px;
  font-size: 17px;
}
.collection-heading p,
.collection-path {
  color: var(--gray-600);
  font-size: 13px;
}
.collection-heading p {
  margin: 0;
}
.collection-path {
  margin: 16px 0;
  overflow-wrap: anywhere;
}
.collection-toolbar {
  flex-wrap: wrap;
  padding: 16px 0;
  border-bottom: 1px solid var(--gray-200);
}
.collection-toolbar > span {
  flex: 1;
  color: var(--gray-600);
  font-size: 13px;
}
.collection-row {
  padding: 16px 0;
  border-bottom: 1px solid var(--gray-100);
}
.collection-copy {
  flex: 1;
  min-width: 0;
}
.collection-copy strong {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
  font-weight: 500;
}
.collection-copy small {
  display: block;
  margin-top: 5px;
  color: var(--gray-600);
}
.collection-panel :deep(.ant-btn) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.collection-panel :deep(.ant-empty) {
  margin: 48px 0;
}
@media (max-width: 640px) {
  .collection-panel {
    padding: 16px;
  }
  .collection-heading,
  .collection-row {
    flex-wrap: wrap;
  }
  .collection-heading > div {
    min-width: 70%;
  }
  .collection-row > button {
    margin-left: 28px;
  }
}
</style>
