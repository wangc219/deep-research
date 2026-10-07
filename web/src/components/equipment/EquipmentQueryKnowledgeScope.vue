<script setup>
import { computed, ref } from 'vue'
import {
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Database,
  LoaderCircle,
  Search,
  X
} from '@lucide/vue'
import { toggleKnowledgeSelection } from '@/utils/equipmentQueries'

const props = defineProps({
  databases: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  enabled: { type: Boolean, default: true },
  selectedIds: { type: Array, default: () => [] }
})

const emit = defineEmits(['update:enabled', 'update:selectedIds'])
const open = ref(false)
const searchValue = ref('')

const selectedSet = computed(() => new Set(props.selectedIds))
const databaseById = computed(() => new Map(props.databases.map((item) => [item.kb_id, item])))
const visibleDatabases = computed(() => {
  const keyword = searchValue.value.trim().toLowerCase()
  if (!keyword) return props.databases
  return props.databases.filter((item) => `${item.name || ''} ${item.description || ''}`.toLowerCase().includes(keyword))
})

const toggleKnowledge = (knowledgeId) => {
  emit('update:selectedIds', toggleKnowledgeSelection(props.selectedIds, knowledgeId))
}
</script>

<template>
  <section class="query-knowledge-scope" :class="enabled ? 'enabled' : 'disabled'">
    <header>
      <div>
        <Database :size="16" />
        <span>
          <b>知识库辅助</b>
          <small>借鉴智能对话的检索方式，仅提供运行级候选范围</small>
        </span>
      </div>
      <div class="query-knowledge-actions">
        <button
          type="button"
          class="query-knowledge-enable"
          :class="{ active: enabled }"
          :aria-pressed="enabled"
          @click="emit('update:enabled', !enabled)"
        >
          <CheckCircle2 v-if="enabled" :size="13" />
          <X v-else :size="13" />
          {{ enabled ? '按需可用' : '已关闭' }}
        </button>
        <button
          type="button"
          class="query-knowledge-expand"
          :aria-expanded="open"
          :aria-label="open ? '收起知识库选择' : '展开知识库选择'"
          @click="open = !open"
        >
          <ChevronDown :size="15" />
        </button>
      </div>
    </header>

    <div class="query-knowledge-summary">
      <span v-if="!enabled">本次 Query 与后续研究均不开放知识库检索。</span>
      <span v-else-if="selectedIds.length">仅允许从选中的 {{ selectedIds.length }} 个知识库按需检索。</span>
      <span v-else>未限定具体库：保留原默认行为，可从当前有权访问的知识库中按需检索。</span>
      <small>不会自动检索、不会预取文档，也不会把知识库内容强行注入动态蜂群 Agent 上下文。</small>
    </div>

    <div v-if="enabled && selectedIds.length" class="query-knowledge-chips">
      <span v-for="knowledgeId in selectedIds" :key="knowledgeId">
        @{{ databaseById.get(knowledgeId)?.name || '已绑定知识库' }}
        <button type="button" aria-label="移除此知识库" @click="toggleKnowledge(knowledgeId)">
          <X :size="11" />
        </button>
      </span>
      <button type="button" @click="emit('update:selectedIds', [])">恢复全部可见</button>
    </div>

    <div v-if="open" class="query-knowledge-picker">
      <div class="query-knowledge-picker-toolbar">
        <label>
          <Search :size="14" />
          <input v-model="searchValue" placeholder="搜索可访问知识库">
        </label>
        <em>{{ selectedIds.length ? `已选 ${selectedIds.length}/64` : '全部可见' }}</em>
      </div>
      <p v-if="!enabled" class="query-knowledge-state">
        <X :size="14" />知识库能力已关闭；重新启用后可继续选择范围。
      </p>
      <p v-else-if="loading" class="query-knowledge-state">
        <LoaderCircle class="spin" :size="14" />正在读取可访问知识库…
      </p>
      <p v-else-if="error" class="query-knowledge-state error">
        <CircleAlert :size="14" />{{ error }}；不影响保持默认范围继续执行。
      </p>
      <div v-else-if="visibleDatabases.length" class="query-knowledge-options">
        <label
          v-for="item in visibleDatabases"
          :key="item.kb_id"
          :title="item.description || item.name"
        >
          <input
            type="checkbox"
            :checked="selectedSet.has(item.kb_id)"
            :disabled="!selectedSet.has(item.kb_id) && selectedIds.length >= 64"
            @change="toggleKnowledge(item.kb_id)"
          >
          <span>
            <b>@{{ item.name }}</b>
            <small>{{ item.description || (item.supports_documents ? '可按需检索' : '外部知识源') }}</small>
          </span>
        </label>
      </div>
      <p v-else class="query-knowledge-state">
        <Database :size="14" />{{ searchValue.trim() ? '没有匹配的知识库。' : '当前没有可访问的知识库。' }}
      </p>
    </div>
  </section>
</template>
