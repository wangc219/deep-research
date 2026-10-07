<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import {
  CloseOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  LeftOutlined,
  ReloadOutlined,
  RightOutlined,
  SearchOutlined,
  StarFilled
} from '@ant-design/icons-vue'
import { equipmentApi } from '@/apis/equipment_api'
import {
  favoriteDimensions,
  favoriteDisplayRow,
  favoriteModules,
  favoriteRowId,
  favoriteSourceUnavailable
} from '@/utils/equipmentFavorites'

const router = useRouter()
const PAGE_SIZE = 12
const rows = ref([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const error = ref('')
const query = ref('')
const capabilityType = ref('all')
const editingId = ref('')
const savingId = ref('')
const deletingIds = ref(new Set())
const reading = ref(null)
const draft = reactive({ display_name: '', note: '', tags: '' })
let loadSequence = 0
let filterTimer = null

const maxPage = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const pageSummary = computed(() => `第 ${page.value} / ${maxPage.value} 页 · 共 ${total.value} 条`)

const load = async (targetPage = 1) => {
  const sequence = ++loadSequence
  loading.value = true
  error.value = ''
  try {
    const payload = await equipmentApi.listFavoriteCards({
      scope: 'private',
      limit: PAGE_SIZE,
      offset: (targetPage - 1) * PAGE_SIZE,
      search: query.value.trim() || undefined,
      capability_type: capabilityType.value === 'all' ? undefined : capabilityType.value
    })
    if (sequence !== loadSequence) return
    const items = [payload?.items, payload?.favorites, payload?.results, payload?.rows]
      .find(Array.isArray) || []
    rows.value = items.map(favoriteDisplayRow)
    total.value = Number(payload?.total ?? items.length)
    page.value = targetPage
  } catch (reason) {
    if (sequence === loadSequence) error.value = reason?.message || '收藏加载失败，请重试'
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

watch([query, capabilityType], () => {
  window.clearTimeout(filterTimer)
  filterTimer = window.setTimeout(() => load(1), 250)
})

const startEdit = (item) => {
  editingId.value = favoriteRowId(item)
  draft.display_name = String(item.display_name || item.name || item.title || '').slice(0, 400)
  draft.note = String(item.note || '').slice(0, 4000)
  draft.tags = Array.isArray(item.tags) ? item.tags.join(', ') : ''
}

const cancelEdit = () => {
  editingId.value = ''
  draft.display_name = ''
  draft.note = ''
  draft.tags = ''
}

const saveEdit = async (item) => {
  const id = favoriteRowId(item)
  if (!id || savingId.value) return
  savingId.value = id
  try {
    const payload = {
      display_name: draft.display_name.trim().slice(0, 400),
      note: draft.note.trim().slice(0, 4000),
      tags: [...new Set(draft.tags.split(/[,，]/).map((value) => value.trim()).filter(Boolean))].slice(0, 20)
    }
    const result = await equipmentApi.updateFavoriteCard(id, payload)
    const saved = result?.favorite || result || {}
    rows.value = rows.value.map((row) =>
      favoriteRowId(row) === id ? favoriteDisplayRow({ ...row, ...saved }) : row
    )
    cancelEdit()
    message.success('收藏卡片信息已更新')
  } catch (reason) {
    message.error(reason?.status === 403 ? '当前身份没有编辑该收藏的权限' : reason?.message || '保存失败')
  } finally {
    savingId.value = ''
  }
}

const remove = (item) => {
  const id = favoriteRowId(item)
  if (!id || deletingIds.value.has(id)) return
  Modal.confirm({
    title: '取消收藏？',
    content: '只会删除收藏记录，不会删除原任务和能力画像。',
    okText: '取消收藏',
    okType: 'danger',
    cancelText: '保留',
    async onOk() {
      deletingIds.value = new Set([...deletingIds.value, id])
      try {
        await equipmentApi.deleteFavoriteCard(id)
        const nextTotal = Math.max(0, total.value - 1)
        const nextPage = Math.min(page.value, Math.max(1, Math.ceil(nextTotal / PAGE_SIZE)))
        await load(nextPage)
        message.success('已取消收藏')
      } catch (reason) {
        message.error(reason?.status === 403 ? '当前身份没有删除该收藏的权限' : reason?.message || '取消收藏失败')
      } finally {
        const next = new Set(deletingIds.value)
        next.delete(id)
        deletingIds.value = next
      }
    }
  })
}

const openSource = (item) => {
  if (!item.run_id || favoriteSourceUnavailable(item)) return
  router.push({
    path: '/equipment/capabilities',
    query: { run: item.run_id, ...(item.card_key ? { cap: item.card_key } : {}) }
  })
}

const openModule = (item, index) => {
  const modules = favoriteModules(item)
  if (!modules[index]) return
  reading.value = { modules, index, item }
}

const moveReader = (delta) => {
  if (!reading.value) return
  const index = reading.value.index + delta
  if (index < 0 || index >= reading.value.modules.length) return
  reading.value = { ...reading.value, index }
}

const handleReaderKey = (event) => {
  if (!reading.value) return
  if (event.key === 'Escape') reading.value = null
  if (event.key === 'ArrowLeft') moveReader(-1)
  if (event.key === 'ArrowRight') moveReader(1)
}

const displayName = (item) => item.display_name || item.name || item.title || '未命名能力画像'
const sourceLabel = (item) => {
  if (item.source_deleted || /deleted|删除/i.test(String(item.source_status || ''))) return '原任务已删除'
  if (/archiv|归档/i.test(String(item.source_status || ''))) return '来源任务已归档'
  return item.source_topic || item.run_id || '来源任务未知'
}

onMounted(() => {
  window.addEventListener('keydown', handleReaderKey)
  load()
})

onBeforeUnmount(() => {
  window.clearTimeout(filterTimer)
  window.removeEventListener('keydown', handleReaderKey)
})
</script>

<template>
  <section class="favorites-page">
    <header class="page-heading">
      <div>
        <span>能力资产</span>
        <h1>收藏</h1>
        <p>保存完整能力画像快照，来源任务归档或删除后仍可独立审阅。</p>
      </div>
      <a-button :loading="loading" @click="load(page)"><ReloadOutlined />刷新</a-button>
    </header>

    <section class="favorites-shell">
      <header class="favorites-header">
        <div>
          <span class="eyebrow"><StarFilled />能力画像收藏</span>
          <h2>个人收藏</h2>
          <p>{{ total }} 张完整能力画像快照 · 按当前账户隔离</p>
        </div>
      </header>

      <div class="favorites-filters">
        <a-input v-model:value="query" allow-clear placeholder="搜索收藏名称">
          <template #prefix><SearchOutlined /></template>
        </a-input>
        <a-select
          v-model:value="capabilityType"
          :options="[
            { value: 'all', label: '全部能力类型' },
            { value: 'new_capability', label: '新能力' },
            { value: 'upgrade', label: '能力升级' }
          ]"
        />
      </div>

      <a-alert v-if="error" class="favorites-error" type="error" show-icon :message="error">
        <template #action><a-button size="small" @click="load(page)">重试</a-button></template>
      </a-alert>

      <div v-if="loading && !rows.length" class="favorites-loading"><a-spin />正在加载收藏…</div>
      <a-empty
        v-else-if="!rows.length"
        :description="query || capabilityType !== 'all' ? '没有匹配的收藏' : '还没有收藏完整能力画像'"
      >
        <a-button @click="router.push('/equipment/capabilities')">去能力画像页看看</a-button>
      </a-empty>

      <div v-else class="favorites-list">
        <article
          v-for="item in rows"
          :key="favoriteRowId(item)"
          class="favorite-card"
          :class="{ 'source-unavailable': favoriteSourceUnavailable(item) }"
        >
          <header>
            <div>
              <div class="favorite-title">
                <span><StarFilled />已收藏</span>
                <h3>{{ displayName(item) }}</h3>
              </div>
              <div class="favorite-meta">
                <em v-if="item.equipment_form || item.equipment_category">{{ item.equipment_form || item.equipment_category }}</em>
                <em>{{ item.capability_type === 'upgrade' ? '能力升级' : '新能力' }}</em>
                <em v-for="tag in item.tags || []" :key="tag">#{{ tag }}</em>
              </div>
            </div>
            <div class="favorite-actions">
              <a-button :disabled="favoriteSourceUnavailable(item)" @click="openSource(item)"><EyeOutlined />查看原卡</a-button>
              <a-button @click="startEdit(item)"><EditOutlined />编辑</a-button>
              <a-button danger :loading="deletingIds.has(favoriteRowId(item))" @click="remove(item)"><DeleteOutlined />取消收藏</a-button>
            </div>
          </header>

          <form v-if="editingId === favoriteRowId(item)" class="favorite-edit" @submit.prevent="saveEdit(item)">
            <label><span>显示名称</span><a-input v-model:value="draft.display_name" :maxlength="400" /></label>
            <label><span>备注</span><a-textarea v-model:value="draft.note" :maxlength="4000" :rows="3" /></label>
            <label><span>标签</span><a-input v-model:value="draft.tags" :maxlength="1200" placeholder="用逗号分隔，例如：重点、待复核" /></label>
            <div><a-button @click="cancelEdit">取消</a-button><a-button type="primary" html-type="submit" :loading="savingId === favoriteRowId(item)">保存</a-button></div>
          </form>

          <aside v-if="item.note" class="favorite-note"><b><EditOutlined />备注</b><p>{{ item.note }}</p></aside>
          <div v-if="favoriteDimensions(item.capability_classification).length" class="favorite-dimensions">
            <b>维度</b>
            <span
              v-for="(dimension, index) in favoriteDimensions(item.capability_classification)"
              :key="dimension"
              :class="{ primary: index === 0 }"
            >{{ dimension }}</span>
          </div>
          <div v-if="favoriteModules(item).length" class="favorite-modules" aria-label="五模块能力画像">
            <button v-for="(module, index) in favoriteModules(item)" :key="module.key" type="button" @click="openModule(item, index)">
              <span><b>{{ module.label }}</b><small>{{ module.text }}</small></span><RightOutlined />
            </button>
          </div>
          <div v-else class="favorite-empty">该收藏未保存可展示的画像正文。</div>
          <footer><span>{{ sourceLabel(item) }}</span><time>{{ item.created_at ? new Date(item.created_at).toLocaleString('zh-CN', { hour12: false }) : '—' }}</time></footer>
        </article>
      </div>

      <footer v-if="maxPage > 1" class="favorites-pager">
        <span>{{ pageSummary }}</span>
        <a-button :disabled="page <= 1 || loading" @click="load(page - 1)"><LeftOutlined />上一页</a-button>
        <a-button :disabled="page >= maxPage || loading" @click="load(page + 1)">下一页<RightOutlined /></a-button>
      </footer>
    </section>

    <div v-if="reading" class="reader-backdrop" @mousedown.self="reading = null">
      <article class="reader" role="dialog" aria-modal="true" aria-labelledby="favorite-reader-title">
        <header><div><span>{{ reading.index + 1 }} / {{ reading.modules.length }}</span><h3 id="favorite-reader-title">{{ reading.modules[reading.index].label }}</h3></div><button type="button" aria-label="关闭" @click="reading = null"><CloseOutlined /></button></header>
        <p>{{ reading.modules[reading.index].text }}</p>
        <footer class="reader-actions" aria-label="能力画像栏目导航">
          <button class="reader-nav previous" :disabled="reading.index === 0" @click="moveReader(-1)"><LeftOutlined />上一栏</button>
          <span>第 {{ reading.index + 1 }} 栏，共 {{ reading.modules.length }} 栏</span>
          <button class="reader-nav next" :disabled="reading.index === reading.modules.length - 1" @click="moveReader(1)">下一栏<RightOutlined /></button>
        </footer>
      </article>
    </div>
  </section>
</template>

<style scoped>
.favorites-page{display:grid;gap:16px;max-width:1240px;margin:0 auto;padding:20px 24px 40px}.page-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.page-heading span,.eyebrow{color:#5653d2;font-size:12px;font-weight:750}.page-heading h1{margin:4px 0;color:var(--text-color,#26344e);font-size:28px}.page-heading p,.favorites-header p{margin:0;color:#78859a}.favorites-shell{overflow:hidden;border:1px solid #dfe6f1;border-radius:12px;background:var(--component-background,#fff);box-shadow:0 8px 30px rgba(39,53,82,.05)}.favorites-header{padding:20px 22px;border-bottom:1px solid #e7ebf3;background:linear-gradient(135deg,#fbfcff,#f4f7ff)}.favorites-header h2{margin:5px 0;color:#26344e;font-size:22px}.eyebrow{display:flex;align-items:center;gap:6px}.favorites-filters{display:flex;gap:10px;padding:13px 16px;border-bottom:1px solid #edf1f5;background:#fafbfd}.favorites-filters :deep(.ant-input-affix-wrapper){flex:1}.favorites-filters :deep(.ant-select){width:180px}.favorites-error{margin:14px 16px}.favorites-loading{display:flex;align-items:center;justify-content:center;gap:10px;min-height:260px;color:#71809a}.favorites-list{display:grid;gap:14px;padding:16px;background:#f8faff}.favorite-card{overflow:hidden;border:1px solid #dbe3f1;border-radius:10px;background:#fff;box-shadow:0 4px 16px rgba(51,73,124,.045)}.favorite-card.source-unavailable{border-color:#eadbb9}.favorite-card>header{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:14px 16px 12px;border-bottom:1px solid #e8edf4;background:linear-gradient(135deg,#fbfcff,#f6f8fd)}.favorite-title{display:flex;align-items:center;gap:8px}.favorite-title>span{display:flex;align-items:center;gap:4px;padding:4px 7px;border:1px solid #ead18b;border-radius:999px;background:#fff8df;color:#a97814;font-size:10px;font-weight:750}.favorite-title h3{margin:0;color:#26344e;font-size:17px}.favorite-meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.favorite-meta em,.favorite-dimensions span{padding:4px 8px;border:1px solid #dce4f2;border-radius:999px;background:#fff;color:#63718a;font-size:10px;font-style:normal}.favorite-actions{display:flex;gap:7px}.favorite-edit{display:grid;gap:10px;padding:14px 18px;border-bottom:1px solid #e8edf4}.favorite-edit label{display:grid;gap:5px}.favorite-edit label>span{color:#536078;font-size:11px;font-weight:700}.favorite-edit>div{display:flex;justify-content:flex-end;gap:7px}.favorite-note{margin:12px 16px 0;padding:10px 12px;border-left:3px solid #aaa9e9;border-radius:7px;background:#fbfcff}.favorite-note b{display:flex;align-items:center;gap:5px;color:#5553bf;font-size:10px}.favorite-note p{margin:5px 0 0;color:#5e6c84;white-space:pre-wrap}.favorite-dimensions{display:flex;align-items:center;flex-wrap:wrap;gap:6px;padding:11px 16px 0}.favorite-dimensions b{font-size:10px}.favorite-dimensions span.primary{border-color:#afaef0;background:#eef2ff;color:#4c49c5;font-weight:700}.favorite-modules{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin:12px 16px 0}.favorite-modules button{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;min-height:104px;padding:13px 12px;border:1px solid #dfe5f1;border-radius:10px;background:#f8faff;text-align:left;cursor:pointer}.favorite-modules button:hover{border-color:#a09ee8;background:#f5f7ff}.favorite-modules button span{display:grid;gap:7px;min-width:0}.favorite-modules b{color:#4f4dc3;font-size:11px}.favorite-modules small{display:-webkit-box;overflow:hidden;color:#65738b;font-size:10px;line-height:1.55;-webkit-box-orient:vertical;-webkit-line-clamp:3}.favorite-empty{margin:14px 16px;color:#8290a5}.favorite-card>footer{display:flex;justify-content:space-between;gap:12px;margin:11px 16px 0;padding:9px 0 12px;border-top:1px solid #edf1f5;color:#8a96aa;font-size:10px}.favorites-pager{display:flex;align-items:center;gap:8px;padding:11px 16px}.favorites-pager>span{margin-right:auto;color:#7b879b;font-size:10px}.reader-backdrop{position:fixed;inset:0;z-index:1400;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(24,31,50,.46);backdrop-filter:blur(4px)}.reader{display:grid;width:min(760px,calc(100% - 120px));max-height:78vh;overflow:hidden;border-radius:16px;background:#fff;box-shadow:0 28px 80px rgba(25,38,78,.28)}.reader>header{display:flex;align-items:center;justify-content:space-between;padding:18px 20px;background:linear-gradient(135deg,#fbfcff,#f2f5ff)}.reader>header>div{display:flex;align-items:center;gap:10px}.reader>header span{padding:5px 8px;border-radius:7px;background:#5653d2;color:#fff;font-size:10px}.reader h3{margin:0;color:#334a9d}.reader header button{border:0;background:transparent;cursor:pointer}.reader>p{margin:0;padding:22px 24px 26px;overflow:auto;color:#3f4e68;font-size:14px;line-height:1.95;white-space:pre-wrap}.reader-nav{position:absolute;top:50%;display:flex;align-items:center;gap:4px;padding:12px;border:1px solid #cfd9ef;border-radius:12px;background:#fff;color:#5452c3;cursor:pointer}.reader-nav.previous{left:max(14px,calc(50% - 448px))}.reader-nav.next{right:max(14px,calc(50% - 448px))}.reader-nav:disabled{opacity:.35}.dark .favorites-header,.dark .favorite-card>header{background:#20232b}.dark .favorites-list,.dark .favorites-filters{background:#17191f}.dark .favorite-card,.dark .favorites-shell,.dark .reader{background:#1f222a}.dark .favorite-title h3,.dark .favorites-header h2,.dark .reader>p{color:#e6e9ef}@media(max-width:1050px){.favorite-modules{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:700px){.favorites-page{padding:14px 12px 90px}.page-heading,.favorite-card>header{flex-direction:column}.favorites-filters{flex-direction:column}.favorites-filters :deep(.ant-select){width:100%}.favorite-actions{width:100%;flex-wrap:wrap}.favorite-modules{grid-template-columns:1fr}.favorite-card>footer{align-items:flex-start;flex-direction:column}.reader-backdrop{padding:12px 12px 82px}.reader{width:100%;max-height:72vh}.reader-nav{top:auto;bottom:14px;width:calc(50% - 20px);justify-content:center}.reader-nav.previous{left:12px}.reader-nav.next{right:12px}}
.reader{grid-template-rows:auto minmax(0,1fr) auto}
.reader>p{min-height:0}
.reader-actions{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:12px;padding:12px 16px;border-top:1px solid #e8edf5;background:#f8faff}
.reader-actions>span{color:#7a879d;font-size:11px;text-align:center}
.reader-nav{position:static;top:auto;bottom:auto;display:flex;align-items:center;justify-content:center;gap:6px;width:auto;min-width:96px;min-height:40px;padding:0 14px;border:1px solid #cfd9ef;border-radius:10px;background:#fff;color:#5452c3;box-shadow:none;cursor:pointer;transform:none}
.reader-nav.previous,.reader-nav.next{right:auto;left:auto}
.reader-nav:hover:not(:disabled){border-color:#a09ee8;background:#f3f5ff;transform:translateY(-1px)}
.reader-nav:disabled{cursor:not-allowed;opacity:.35}
.dark .reader-actions{border-top-color:#353a46;background:#242832}
.dark .reader-actions>span{color:#aab3c3}
@media(max-width:700px){.reader-backdrop{padding:12px}.reader{max-height:calc(100dvh - 24px)}.reader-actions{grid-template-columns:1fr 1fr;gap:8px;padding:10px 12px}.reader-actions>span{display:none}.reader-nav{bottom:auto;width:100%;min-height:42px}.reader-nav.previous,.reader-nav.next{right:auto;left:auto}.reader-nav:hover:not(:disabled){transform:none}}
</style>
