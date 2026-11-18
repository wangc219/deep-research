<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { useRoute } from 'vue-router'
import { databaseApi } from '@/apis/knowledge_api'
import { knowledgeGovernanceApi } from '@/apis/knowledge_governance_api'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const route = useRoute()
const loading = ref(false)
const error = ref('')
const databases = ref([])
const kbId = ref()
const categories = ref([])
const uncategorized = ref({ name: '未分类', stats: {} })
const sources = ref([])
const staging = ref([])
const stagingTotal = ref(0)
const stagingStatus = ref('pending')
const selectedItems = ref([])
const categoryOpen = ref(false)
const editingCategoryId = ref(null)
const sourceOpen = ref(false)
const editingSourceId = ref(null)
const sourceSaving = ref(false)
const sourceRuns = reactive({})
const categoryForm = reactive({ name: '', parent_id: null, description: '', sort_order: 0 })
const sourceForm = reactive({
  name: '',
  source_type: 'web_search',
  category_id: null,
  configText: '{\n  "topics": ["无人系统", "导弹技术", "反无人系统"],\n  "count": 10\n}',
  credentialText: '',
  cron_expression: '0 8 * * *',
  timezone: 'Asia/Shanghai',
  notify_on_new: true,
  enabled: true
})

const categoryOptions = computed(() =>
  categories.value
    .filter((item) => item.active)
    .map((item) => ({ value: item.id, label: item.name }))
)
const selectedKb = computed(() => databases.value.find((item) => item.kb_id === kbId.value))
const manageable = computed(() => databases.value.filter((item) => item.can_manage))
const focusedStagingId = computed(() => String(route.query.staging || ''))
const categoryRows = computed(() => {
  const children = new Map()
  const visible = new Set(categories.value.map((item) => item.id))
  for (const item of categories.value) {
    const parent = visible.has(item.parent_id) ? item.parent_id : null
    if (!children.has(parent)) children.set(parent, [])
    children.get(parent).push(item)
  }
  const rows = []
  const visited = new Set()
  const append = (parent, depth) => {
    for (const item of children.get(parent) || []) {
      if (visited.has(item.id)) continue
      visited.add(item.id)
      rows.push({ ...item, depth })
      append(item.id, depth + 1)
    }
  }
  append(null, 0)
  // 兼容迁移前可能存在的孤儿或异常循环数据，避免整支分类在界面中消失。
  for (const item of categories.value) {
    if (visited.has(item.id)) continue
    visited.add(item.id)
    rows.push({ ...item, depth: 0 })
    append(item.id, 1)
  }
  return rows
})
const sourceCategoryOptions = computed(() => {
  const rootId = selectedKb.value?.category_id
  if (!rootId) return categoryOptions.value
  const allowed = new Set([rootId])
  let changed = true
  while (changed) {
    changed = false
    for (const item of categories.value) {
      if (item.active && allowed.has(item.parent_id) && !allowed.has(item.id)) {
        allowed.add(item.id)
        changed = true
      }
    }
  }
  return categoryOptions.value.filter((item) => allowed.has(item.value))
})

async function loadBase() {
  loading.value = true
  error.value = ''
  try {
    const [dbResult, categoryResult] = await Promise.all([
      databaseApi.getDatabases(),
      knowledgeGovernanceApi.categories(userStore.isAdmin)
    ])
    databases.value = dbResult.databases || []
    categories.value = categoryResult.flat || []
    uncategorized.value = categoryResult.uncategorized || { name: '未分类', stats: {} }
    const requestedKb = String(route.query.kb || '')
    if (manageable.value.some((item) => item.kb_id === requestedKb)) kbId.value = requestedKb
    if (!manageable.value.some((item) => item.kb_id === kbId.value)) {
      kbId.value = manageable.value[0]?.kb_id
    }
    if (focusedStagingId.value) stagingStatus.value = ''
    await loadKnowledgeScope()
  } catch (cause) {
    error.value = cause.message || '知识治理数据加载失败'
  } finally {
    loading.value = false
  }
}

async function loadKnowledgeScope() {
  if (!kbId.value) {
    sources.value = []
    staging.value = []
    stagingTotal.value = 0
    return
  }
  const [sourceResult, stagingResult] = await Promise.all([
    knowledgeGovernanceApi.sources(kbId.value),
    knowledgeGovernanceApi.staging({
      kb_id: kbId.value,
      review_status: stagingStatus.value,
      page: 1,
      page_size: 100
    })
  ])
  sources.value = sourceResult.items || []
  staging.value = stagingResult.items || []
  stagingTotal.value = stagingResult.total || 0
  selectedItems.value = selectedItems.value.filter((id) => staging.value.some((item) => item.id === id))
}

function openCategory(item = null) {
  editingCategoryId.value = item?.id || null
  Object.assign(categoryForm, {
    name: item?.name || '',
    parent_id: item?.parent_id || null,
    description: item?.description || '',
    sort_order: item?.sort_order || 0
  })
  categoryOpen.value = true
}

async function saveCategory() {
  try {
    if (editingCategoryId.value) {
      await knowledgeGovernanceApi.updateCategory(editingCategoryId.value, { ...categoryForm })
    } else {
      await knowledgeGovernanceApi.createCategory({ ...categoryForm })
    }
    categoryOpen.value = false
    message.success(editingCategoryId.value ? '分类已更新' : '分类已创建')
    await loadBase()
  } catch (cause) {
    message.error(cause.message || '分类保存失败')
  }
}

function deleteCategory(item) {
  Modal.confirm({
    title: `删除分类“${item.name}”？`,
    content: '已有子级或知识资产引用的分类不能删除，可改为停用。',
    async onOk() {
      await knowledgeGovernanceApi.deleteCategory(item.id)
      await loadBase()
    }
  })
}

async function toggleCategory(item) {
  await knowledgeGovernanceApi.updateCategory(item.id, { active: !item.active })
  await loadBase()
}

function resetSourceConfig(type) {
  const defaults = {
    web_search: { topics: ['无人系统', '导弹技术', '反无人系统'], count: 10, time_range: 'month' },
    website: { urls: ['https://example.com'], max_depth: 0, max_pages: 20 },
    postgresql: { table: '', primary_key: 'id', content_columns: [], columns: [], max_rows: 200 },
    mysql: { table: '', primary_key: 'id', content_columns: [], columns: [], max_rows: 200 },
    upload: {}
  }
  sourceForm.configText = JSON.stringify(defaults[type] || {}, null, 2)
  sourceForm.credentialText = ''
}

function openSource(item = null) {
  editingSourceId.value = item?.id || null
  Object.assign(sourceForm, {
    name: item?.name || '',
    source_type: item?.source_type || 'web_search',
    category_id: item?.category_id || selectedKb.value?.category_id || null,
    configText: JSON.stringify(item?.config || {}, null, 2),
    credentialText: '',
    cron_expression: item?.cron_expression || '',
    timezone: item?.timezone || 'Asia/Shanghai',
    notify_on_new: item?.notify_on_new ?? true,
    enabled: item?.enabled ?? true
  })
  if (!item) resetSourceConfig('web_search')
  sourceOpen.value = true
}

async function saveSource() {
  sourceSaving.value = true
  try {
    const config = JSON.parse(sourceForm.configText || '{}')
    const credential = sourceForm.credentialText ? JSON.parse(sourceForm.credentialText) : null
    const payload = {
      name: sourceForm.name,
      category_id: sourceForm.category_id,
      config,
      cron_expression: sourceForm.cron_expression || null,
      timezone: sourceForm.timezone,
      notify_on_new: sourceForm.notify_on_new,
      enabled: sourceForm.enabled
    }
    if (credential) payload.credential = credential
    if (editingSourceId.value) {
      await knowledgeGovernanceApi.updateSource(editingSourceId.value, payload)
    } else {
      await knowledgeGovernanceApi.createSource({
        ...payload,
        kb_id: kbId.value,
        source_type: sourceForm.source_type
      })
    }
    sourceOpen.value = false
    message.success(editingSourceId.value ? '来源配置已更新' : '来源已创建，凭据已独立加密保存')
    await loadKnowledgeScope()
  } catch (cause) {
    message.error(cause instanceof SyntaxError ? '配置或凭据 JSON 格式错误' : cause.message)
  } finally {
    sourceSaving.value = false
  }
}

async function sourceAction(action, item) {
  try {
    if (action === 'run') {
      await knowledgeGovernanceApi.runSource(item.id)
      message.success('采集任务已提交')
    } else if (action === 'test') {
      const result = await knowledgeGovernanceApi.testSource(item.id)
      message.success(`连接成功，样例 ${result.sample_count} 条`)
    } else if (action === 'toggle') {
      await knowledgeGovernanceApi.updateSource(item.id, { enabled: !item.enabled })
    } else if (action === 'runs') {
      const result = await knowledgeGovernanceApi.sourceRuns(item.id)
      sourceRuns[item.id] = result.items || []
      return
    }
    await loadKnowledgeScope()
  } catch (cause) {
    message.error(cause.message || '来源操作失败')
  }
}

function deleteSource(item) {
  Modal.confirm({
    title: `删除来源“${item.name}”？`,
    content: '来源运行和暂存项将删除，已经正式入库的文档会保留。',
    async onOk() {
      await knowledgeGovernanceApi.deleteSource(item.id)
      delete sourceRuns[item.id]
      await loadKnowledgeScope()
    }
  })
}

async function review(decision) {
  if (!selectedItems.value.length) return
  try {
    const result = await knowledgeGovernanceApi.reviewStaging({
      kb_id: kbId.value,
      ids: selectedItems.value,
      decision,
      note: '',
      category_id: null
    })
    const submitted = (result.items || []).filter((item) => item.task_id).length
    message.success(decision === 'approved' ? `${submitted} 项已提交解析和索引` : '所选证据已拒绝')
    selectedItems.value = []
    await loadKnowledgeScope()
  } catch (cause) {
    message.error(cause.message || '暂存审核失败')
  }
}

watch(kbId, () => loadKnowledgeScope())
watch(stagingStatus, () => loadKnowledgeScope())
onMounted(loadBase)
</script>

<template>
  <main class="governance-page">
    <header>
      <div>
        <h2>知识来源治理</h2>
        <p>组织分类树 → 来源配置 → 定时采集 → 暂存审核 → 正式入库。</p>
      </div>
      <a-button :loading="loading" @click="loadBase">刷新</a-button>
    </header>
    <a-alert v-if="error" type="error" :message="error" show-icon />
    <a-spin :spinning="loading">
      <section class="governance-grid">
        <article class="panel categories-panel">
          <div class="panel-heading">
            <div><h3>组织分类树</h3><small>单主分类，标签继续承担交叉属性</small></div>
            <a-button v-if="userStore.isAdmin" size="small" type="primary" @click="openCategory()">新增</a-button>
          </div>
          <a-empty v-if="!categories.length" description="暂无分类，现有资产均视为未分类" />
          <div
            v-if="Object.values(uncategorized.stats || {}).some((value) => Number(value) > 0)"
            class="category-row uncategorized-row"
          >
            <span class="category-title"><b>{{ uncategorized.name }}</b><small>历史资产，不自动猜测分类</small></span>
            <span class="stats">库 {{ uncategorized.stats?.knowledge_bases || 0 }} · 来源 {{ uncategorized.stats?.sources || 0 }} · 文档 {{ uncategorized.stats?.documents || 0 }}</span>
          </div>
          <div v-for="item in categoryRows" :key="item.id" class="category-row">
            <span class="category-title" :style="{ paddingLeft: `${item.depth * 20}px` }"><b><i v-if="item.depth" class="tree-branch">↳</i>{{ item.name }}</b><small>{{ item.active ? '启用' : '已停用' }}</small></span>
            <span class="stats">库 {{ item.stats?.knowledge_bases || 0 }} · 来源 {{ item.stats?.sources || 0 }} · 文档 {{ item.stats?.documents || 0 }}</span>
            <a-space v-if="userStore.isAdmin" class="category-actions" wrap>
              <a-button size="small" @click="openCategory(item)">编辑</a-button>
              <a-button size="small" @click="toggleCategory(item)">{{ item.active ? '停用' : '启用' }}</a-button>
              <a-button size="small" danger @click="deleteCategory(item)">删除</a-button>
            </a-space>
          </div>
        </article>

        <article class="panel sources-panel">
          <div class="panel-heading">
            <div><h3>统一来源与调度</h3><small>数据库仅表/视图映射，网站不使用登录态</small></div>
            <a-button :disabled="!kbId" type="primary" size="small" @click="openSource()">新增来源</a-button>
          </div>
          <a-select v-model:value="kbId" :options="manageable.map((item) => ({ value: item.kb_id, label: item.name }))" placeholder="选择可管理知识库" style="width:100%;margin-bottom:12px" />
          <a-empty v-if="kbId && !sources.length" description="该知识库暂无来源" />
          <div v-for="item in sources" :key="item.id" class="source-row">
            <span><b>{{ item.name }}</b><small>{{ item.source_type }} · {{ item.last_status }} · 下次 {{ item.next_run_at || '未调度' }}</small></span>
            <a-space class="source-actions" wrap>
              <a-button size="small" @click="sourceAction('test', item)">测试</a-button>
              <a-button size="small" type="primary" @click="sourceAction('run', item)">立即运行</a-button>
              <a-button size="small" @click="openSource(item)">编辑</a-button>
              <a-button size="small" @click="sourceAction('runs', item)">运行记录</a-button>
              <a-button size="small" @click="sourceAction('toggle', item)">{{ item.enabled ? '暂停' : '启用' }}</a-button>
              <a-button size="small" danger @click="deleteSource(item)">删除</a-button>
            </a-space>
            <div v-if="sourceRuns[item.id]" class="source-runs">
              <small v-if="!sourceRuns[item.id].length">暂无运行记录</small>
              <small v-for="runItem in sourceRuns[item.id].slice(0, 8)" :key="runItem.id">
                {{ runItem.trigger }} · {{ runItem.status }} · 新增 {{ runItem.stats?.created || 0 }} · 重复 {{ runItem.stats?.duplicates || 0 }} · {{ runItem.created_at }}
              </small>
            </div>
          </div>
        </article>
      </section>

      <section class="panel staging-panel">
        <div class="panel-heading">
          <div><h3>暂存审核</h3><small>待审核内容不会进入正式检索和事实图谱</small></div>
          <a-space class="staging-actions" wrap>
            <a-select v-model:value="stagingStatus" style="width:120px" :options="[
              { value: '', label: '全部状态' },
              { value: 'pending', label: '待审核' }, { value: 'approved', label: '已通过' },
              { value: 'rejected', label: '已拒绝' }, { value: 'duplicate', label: '重复' },
              { value: 'failed', label: '失败' }
            ]" />
            <a-button :disabled="!selectedItems.length" @click="review('rejected')">拒绝</a-button>
            <a-button type="primary" :disabled="!selectedItems.length" @click="review('approved')">通过并入库</a-button>
          </a-space>
        </div>
        <p class="scope-label">{{ selectedKb?.name || '未选择知识库' }} · {{ stagingTotal }} 项</p>
        <a-empty v-if="!staging.length" description="当前筛选下没有暂存证据" />
        <div v-for="item in staging" :key="item.id" class="staging-row" :class="{ focused: focusedStagingId === item.id }">
          <a-checkbox v-model:checked="item._selected" :disabled="item.review_status !== 'pending'" @change="selectedItems = staging.filter((row) => row._selected && row.review_status === 'pending').map((row) => row.id)" />
          <div><b>{{ item.title }}</b><small>版本 {{ item.version }} · {{ item.canonical_url || '数据库/内部来源' }} · {{ item.discovered_at }}</small></div>
          <a-tag>{{ item.review_status }}</a-tag>
        </div>
      </section>
    </a-spin>

    <a-modal v-model:open="categoryOpen" :title="editingCategoryId ? '编辑组织分类' : '新增组织分类'" ok-text="保存" @ok="saveCategory">
      <a-input v-model:value="categoryForm.name" placeholder="分类名称" />
      <a-select v-model:value="categoryForm.parent_id" allow-clear :options="categoryOptions.filter((item) => item.value !== editingCategoryId)" placeholder="父分类（可选）" style="width:100%;margin-top:12px" />
      <a-textarea v-model:value="categoryForm.description" placeholder="说明" style="margin-top:12px" />
      <a-input-number v-model:value="categoryForm.sort_order" placeholder="排序" style="width:100%;margin-top:12px" />
    </a-modal>

    <a-modal v-model:open="sourceOpen" :title="editingSourceId ? '编辑知识来源' : '新增知识来源'" :confirm-loading="sourceSaving" ok-text="保存" width="680px" @ok="saveSource">
      <a-input v-model:value="sourceForm.name" placeholder="来源名称" />
      <a-select v-model:value="sourceForm.source_type" :disabled="Boolean(editingSourceId)" :options="[
        { value: 'upload', label: '手工上传' }, { value: 'postgresql', label: 'PostgreSQL' },
        { value: 'mysql', label: 'MySQL' }, { value: 'website', label: '公开网站' },
        { value: 'web_search', label: 'WebSearch 关注话题' }
      ]" style="width:100%;margin-top:12px" @change="resetSourceConfig" />
      <a-select v-model:value="sourceForm.category_id" allow-clear :options="sourceCategoryOptions" placeholder="来源分类（可选）" style="width:100%;margin-top:12px" />
      <label>来源配置 JSON（不允许密码、Cookie、Token 或任意 SQL）</label>
      <a-textarea v-model:value="sourceForm.configText" :rows="8" />
      <label v-if="['postgresql','mysql'].includes(sourceForm.source_type)">加密凭据 JSON（host/database/username/password/port；编辑时留空表示保留）</label>
      <a-textarea v-if="['postgresql','mysql'].includes(sourceForm.source_type)" v-model:value="sourceForm.credentialText" :rows="4" />
      <a-input v-model:value="sourceForm.cron_expression" placeholder="5 段 cron；留空则不定时" style="margin-top:12px" />
      <a-input v-model:value="sourceForm.timezone" placeholder="IANA 时区" style="margin-top:12px" />
      <a-checkbox v-model:checked="sourceForm.notify_on_new">发现新内容时站内提醒</a-checkbox>
    </a-modal>
  </main>
</template>

<style scoped>
.governance-page{padding:24px;max-width:1440px;margin:auto}.governance-page>header,.panel-heading,.category-row,.source-row,.staging-row{display:flex;align-items:center;gap:12px}.governance-page>header{justify-content:space-between;margin-bottom:18px}.governance-page h2,.panel h3{margin:0}.governance-page p,.panel small{color:var(--gray-600)}.governance-grid{display:grid;grid-template-columns:minmax(300px,.8fr) minmax(480px,1.2fr);gap:16px}.panel{border:1px solid var(--gray-200);border-radius:12px;background:var(--gray-0);padding:18px}.panel-heading{justify-content:space-between;margin-bottom:14px}.panel-heading small,.category-row small,.source-row small,.staging-row small{display:block;margin-top:4px}.category-row,.source-row,.staging-row{border-top:1px solid var(--gray-100);padding:12px 0}.source-row{flex-wrap:wrap}.category-title,.source-row>span:first-child,.staging-row>div{flex:1;min-width:0}.tree-branch{margin-right:7px;color:var(--gray-400);font-style:normal}.source-runs{flex-basis:100%;padding:8px 10px;border-radius:8px;background:var(--gray-50)}.source-runs small{padding:3px 0}.stats,.scope-label{font-size:12px;color:var(--gray-600)}.staging-panel{margin-top:16px}.staging-row b,.staging-row small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.staging-row.focused{margin:0 -8px;padding:12px 8px;border-radius:8px;background:var(--main-50);box-shadow:inset 3px 0 var(--main-color)}label{display:block;margin:12px 0 6px;color:var(--gray-700);font-size:13px}@media(max-width:900px){.governance-grid{grid-template-columns:1fr}.governance-page{padding:14px}.panel-heading{align-items:flex-start;flex-direction:column}}@media(max-width:600px){.governance-page>header{align-items:flex-start}.governance-page>header p{margin-bottom:0}.category-row{align-items:flex-start;flex-wrap:wrap}.category-title{flex-basis:100%;width:100%}.category-row>.stats{flex:1 1 100%}.category-actions,.source-actions,.staging-actions{flex:1 1 100%}.staging-panel .panel-heading{width:100%}.staging-row{align-items:flex-start}.panel{padding:16px}}
</style>
