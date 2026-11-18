<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Archive, Download, FolderOpen, RefreshCw, Upload } from '@lucide/vue'
import { message } from 'ant-design-vue'
import { collectionArtifactApi } from '@/apis/collection_artifact_api'
import { databaseApi } from '@/apis/knowledge_api'
import { knowledgeGovernanceApi } from '@/apis/knowledge_governance_api'
import { useTaskerStore } from '@/stores/tasker'
import WorkspaceFileDrawer from '@/components/workspace/WorkspaceFileDrawer.vue'
import {
  COLLECTION_ARTIFACT_PAGE_SIZES,
  COLLECTION_ARTIFACT_SELECTION_LIMIT,
  filterCollectionArtifactRows,
  paginateCollectionArtifactRows,
  selectCollectionArtifactPage
} from '@/utils/collectionArtifactList'

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
const category = ref()
const categories = ref([])
const failures = ref([])
const archiveFailures = ref([])
const keyword = ref('')
const accountFilter = ref()
const stateFilter = ref('all')
const page = ref(1)
const pageSize = ref(50)
let timer
let disposed = false
const ready = computed(() => items.value.filter((item) => item.available))
const chosen = computed(() => items.value.filter((item) => selected.value.includes(item.id)))
const importable = computed(() => chosen.value.filter((item) => item.import_available))
const accountOptions = computed(() =>
  [...new Set(items.value.map((item) => item.account).filter(Boolean))]
    .sort((left, right) => left.localeCompare(right, 'zh-CN'))
    .map((value) => ({ value, label: value }))
)
const stateOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'downloaded', label: '已下载未入库' },
  { value: 'importing', label: '入库中' },
  { value: 'imported', label: '已入库' },
  { value: 'failed', label: '处理失败' },
  { value: 'missing', label: '工作区文件缺失' }
]
const filteredRows = computed(() =>
  filterCollectionArtifactRows(items.value, {
    query: keyword.value,
    account: accountFilter.value,
    state: stateFilter.value
  })
)
const pagination = computed(() =>
  paginateCollectionArtifactRows(filteredRows.value, page.value, pageSize.value)
)
const pageRows = computed(() => pagination.value.rows)
const pageItems = computed(() =>
  pageRows.value.map((row) => ({ ...row.item, order: row.index }))
)
const pageReadyIds = computed(() =>
  pageRows.value.filter((row) => row.item.available).map((row) => row.item.id)
)
const pageSelectedCount = computed(
  () => pageReadyIds.value.filter((id) => selected.value.includes(id)).length
)
const pageAllSelected = computed(
  () => !!pageReadyIds.value.length && pageSelectedCount.value === pageReadyIds.value.length
)
const pageSelectionIndeterminate = computed(
  () => pageSelectedCount.value > 0 && pageSelectedCount.value < pageReadyIds.value.length
)
const pageSizeOptions = COLLECTION_ARTIFACT_PAGE_SIZES.map(String)
const categoryOptions = computed(() => {
  const rootId = libraries.value.find((item) => item.value === kb.value)?.category_id
  const allowed = new Set(rootId ? [rootId] : categories.value.map((item) => item.id))
  if (rootId) {
    let changed = true
    while (changed) {
      changed = false
      for (const item of categories.value) {
        if (allowed.has(item.parent_id) && !allowed.has(item.id)) {
          allowed.add(item.id)
          changed = true
        }
      }
    }
  }
  return categories.value
    .filter((item) => item.active && allowed.has(item.id))
    .map((item) => ({ value: item.id, label: item.name }))
})
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
    if (!accountOptions.value.some((item) => item.value === accountFilter.value))
      accountFilter.value = undefined
    page.value = pagination.value.page
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
  if (checked && selected.value.length >= COLLECTION_ARTIFACT_SELECTION_LIMIT) {
    message.info('每批最多选择 100 项，请先下载或入库，再清空选择处理下一批')
    return
  }
  selected.value = checked
    ? [...new Set([...selected.value, id])]
    : selected.value.filter((value) => value !== id)
}
function togglePage(checked) {
  const pageIds = new Set(pageReadyIds.value)
  if (!checked) {
    selected.value = selected.value.filter((id) => !pageIds.has(id))
    return
  }
  const result = selectCollectionArtifactPage(selected.value, pageRows.value)
  selected.value = result.ids
  if (result.limitReached)
    message.info('已达到每批 100 项上限，请先下载或入库，再清空选择处理下一批')
}
function clearSelection() {
  selected.value = []
}
async function download() {
  if (!selected.value.length || busy.value) return
  downloading.value = true
  error.value = ''
  archiveFailures.value = []
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
    archiveFailures.value = cause.response?.data?.detail?.failures || []
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
      .map((db) => ({ value: db.kb_id, label: db.name, category_id: db.category_id || null }))
    if (!libraries.value.some((item) => item.value === kb.value)) kb.value = undefined
    const categoryResult = await knowledgeGovernanceApi.categories()
    categories.value = categoryResult.flat || []
    if (!categoryOptions.value.some((item) => item.value === category.value)) category.value = undefined
    failures.value = []
    importOpen.value = true
  } catch (cause) {
    error.value = cause.message || '知识库列表加载失败'
  }
}
function chooseKnowledgeBase() {
  if (!categoryOptions.value.some((item) => item.value === category.value)) category.value = undefined
}
async function submitImport() {
  if (importing.value || !libraries.value.some((item) => item.value === kb.value)) return
  importing.value = true
  const kbId = kb.value
  const register = tasker.createTaskRegistration()
  try {
    const result = await collectionArtifactApi.ingest(
      props.source,
      importable.value.map((item) => item.id),
      kbId,
      category.value || null
    )
    for (const item of result.items || []) {
      if (item.task_id) {
        register({
          id: item.task_id,
          task_id: item.task_id,
          name: `${title.value}入库`,
          status: 'pending',
          task_type: 'knowledge_ingest',
          payload: { kb_id: kbId }
        })
      }
    }
    failures.value = (result.items || [])
      .filter((item) => item.status === 'failed')
      .map((item) => ({ path: items.value.find((row) => row.id === item.id)?.import_path || item.id, error: item.error }))
    if (result.submitted)
      message.success(`${result.submitted} 项已提交入库；下载选择保持不变，可继续批量下载`)
    await refresh()
    if (!failures.value.length) importOpen.value = false
  } finally {
    importing.value = false
  }
}
onMounted(async () => {
  await refresh(true)
  if (!disposed) schedule()
})
watch([keyword, accountFilter, stateFilter], () => {
  page.value = 1
})
watch(
  () => pagination.value.page,
  (value) => {
    if (page.value !== value) page.value = value
  }
)
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
      v-if="archiveFailures.length"
      type="warning"
      message="以下成果未能加入下载包"
      show-icon
    >
      <template #description>
        <div v-for="failure in archiveFailures" :key="`${failure.id}-${failure.path}`">
          {{ failure.title || failure.path || failure.id }}：{{ failure.error }}
          <template v-if="failure.size">（{{ Math.ceil(failure.size / 1024 / 1024) }} MB）</template>
        </div>
      </template>
    </a-alert>
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
    <div class="collection-filters" aria-label="成果筛选">
      <a-input
        v-model:value="keyword"
        allow-clear
        :placeholder="props.source === 'wxchannels' ? '按标题或视频号筛选' : '按标题或公众号筛选'"
        :aria-label="props.source === 'wxchannels' ? '按标题或视频号筛选成果' : '按标题或公众号筛选成果'"
      />
      <a-select
        v-model:value="accountFilter"
        allow-clear
        :options="accountOptions"
        :placeholder="props.source === 'wxchannels' ? '全部视频号' : '全部公众号'"
        aria-label="按来源账号筛选成果"
      />
      <a-select
        v-model:value="stateFilter"
        :options="stateOptions"
        aria-label="按处理状态筛选成果"
      />
    </div>
    <div class="collection-toolbar">
      <a-checkbox
        :disabled="busy || !pageReadyIds.length"
        :checked="pageAllSelected"
        :indeterminate="pageSelectionIndeterminate"
        @change="togglePage($event.target.checked)"
        >选择当前页（{{ pageReadyIds.length }} 项）</a-checkbox
      >
      <span>已选 {{ selected.length }} / 筛选 {{ filteredRows.length }} / 全部 {{ items.length }}</span>
      <a-button v-if="selected.length" size="small" :disabled="busy" @click="clearSelection"
        >清空已选</a-button
      >
      <a-button :disabled="!selected.length || importing" :loading="downloading" @click="download"
        ><Download :size="15" />下载所选成果</a-button
      >
      <a-button type="primary" :disabled="!importable.length || busy" @click="openImport"
        ><Upload :size="15" />一键入库</a-button
      >
    </div>
    <a-spin :spinning="loading && !items.length">
      <a-empty
        v-if="!items.length"
        description="暂无成果，请先批量选择文章下载或视频转录"
      />
      <a-empty v-else-if="!filteredRows.length" description="没有符合当前筛选条件的成果" />
      <div v-for="item in pageItems" :key="item.id" class="collection-row">
        <span class="collection-index" :aria-label="`成果序号 ${item.order}`">#{{ item.order }}</span>
        <a-checkbox
          :checked="selected.includes(item.id)"
          :disabled="busy || !item.available"
          :aria-label="`选择第 ${item.order} 条成果：${item.title}`"
          @change="toggle(item.id, $event.target.checked)"
        />
        <div class="collection-copy">
          <strong :title="item.title">{{ item.title }}</strong
          ><small
            >{{ item.account || title }} ·
            {{ item.available ? '已保存到沙盒工作区' : '工作区文件缺失，请刷新恢复' }} ·
            {{ ({ downloaded: '已下载未入库', importing: '入库中', imported: '已入库', failed: item.failure_stage === 'ingest' ? '入库失败' : '下载失败' })[item.download_state] || '已下载未入库' }}</small
          >
          <small v-if="item.ingestions?.length">
            最近目标：{{ item.ingestions[0].kb_id }} · 任务 {{ item.ingestions[0].task_id }}
          </small>
        </div>
        <a-button size="small" :disabled="!item.available" @click="previewPath = item.primary_path"
          >侧开预览</a-button
        >
      </div>
      <div v-if="filteredRows.length" class="collection-pagination">
        <a-pagination
          v-model:current="page"
          v-model:page-size="pageSize"
          :total="filteredRows.length"
          :page-size-options="pageSizeOptions"
          show-size-changer
          :show-total="(total, range) => `第 ${range[0]}–${range[1]} 条，共 ${total} 条`"
        />
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
        @change="chooseKnowledgeBase"
      />
      <a-select
        v-model:value="category"
        allow-clear
        :options="categoryOptions"
        :disabled="importing"
        placeholder="选择主分类（可选）"
        aria-label="成果分类"
        style="width: 100%; margin-top: 12px"
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
.collection-filters {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(160px, 220px) minmax(150px, 190px);
  gap: 10px;
  margin-top: 16px;
}
.collection-filters :deep(.ant-select) {
  width: 100%;
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
.collection-index {
  width: 50px;
  flex: 0 0 50px;
  color: var(--gray-500);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-align: right;
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
.collection-pagination {
  display: flex;
  justify-content: flex-end;
  padding-top: 18px;
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
  .collection-filters {
    grid-template-columns: 1fr;
  }
  .collection-index {
    width: 42px;
    flex-basis: 42px;
  }
  .collection-pagination {
    justify-content: flex-start;
    overflow-x: auto;
  }
  .collection-row > button {
    margin-left: 28px;
  }
}
</style>
