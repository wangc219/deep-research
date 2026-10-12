<script setup>
import { computed, reactive, watch } from 'vue'
import { filterEvidenceGraph, graphSourceOptions } from './evidenceGraph'

const props = defineProps({
  graph: { type: Array, default: () => [] },
  sources: { type: Array, default: () => [] },
  removedCount: { type: Number, default: 0 }
})
defineEmits(['open-source'])
const filters = reactive({ query: '', kind: 'all', sourceId: '' })
const filteredEdges = computed(() => filterEvidenceGraph(props.graph, filters))
const sourceOptions = computed(() => graphSourceOptions(props.graph, props.sources))
const hasFilters = computed(() => filters.query.trim() || filters.kind !== 'all' || filters.sourceId)
function clearFilters() { Object.assign(filters, { query: '', kind: 'all', sourceId: '' }) }
watch(() => props.graph, clearFilters)
</script>

<template>
  <section class="evidence-graph" aria-label="证据关系探索">
    <h3>证据关系</h3>
    <p class="explanation">按主体、关系或客体查找，并可组合筛选来源与关系类型。原文端点校验只确认名称出现在引文中，不代表关系语义已获独立核实；推断仍需验证。</p>
    <p v-if="removedCount > 0" class="muted">本次另有 {{ removedCount }} 条关系未通过展示校验，已移除。</p>
    <p v-if="!graph.length" class="empty-state">本次没有可展示的证据关系，可能是证据不足或未通过原文与端点校验；补充原始资料后可重新提问。</p>
    <template v-else>
      <div class="filters" role="group" aria-label="筛选证据关系">
        <label class="search-field"><span>搜索主体、关系或客体</span><input v-model="filters.query" type="search" maxlength="200" placeholder="例如：Docling 表格" /></label>
        <label><span>关系类型</span><select v-model="filters.kind"><option value="all">全部类型</option><option value="fact">原文陈述</option><option value="inference">推断</option></select></label>
        <label><span>关系来源</span><select v-model="filters.sourceId"><option value="">全部来源</option><option v-for="source in sourceOptions" :key="source.id" :value="source.id">[{{ source.id }}] {{ source.title }}</option></select></label>
      </div>
      <div class="filter-summary"><p role="status" aria-live="polite">展示 {{ filteredEdges.length }} / {{ graph.length }} 条关系</p><button v-if="hasFilters" type="button" @click="clearFilters">清除筛选</button></div>
      <p v-if="!filteredEdges.length" class="empty-state">没有符合当前筛选的关系。可以更换关键词或清除筛选。</p>
      <div v-for="(edge, i) in filteredEdges" :key="i" class="relation">
        <div class="badges"><span class="badge">{{ edge.kind === 'fact' ? '原文陈述 · 未独立核实' : edge.kind === 'inference' ? '推断 · 待验证' : '类型未知 · 待核实' }}</span><span class="badge">{{ edge.grounding_status === 'endpoints_in_quote' ? '原文端点已校验' : '历史结果 · 端点未校验' }}</span></div>
        <p class="relation-statement"><strong>{{ edge.subject }}</strong><span class="relation-arrow" aria-hidden="true">→</span><span>{{ edge.relation }}</span><span class="relation-arrow" aria-hidden="true">→</span><strong>{{ edge.object }}</strong></p>
        <blockquote v-if="edge.quote">{{ edge.quote }}</blockquote>
        <p v-else class="muted">此历史关系未提供原文引文。</p>
        <a v-if="edge.source_id" :href="`#document-source-${encodeURIComponent(edge.source_id)}`" @click.prevent="$emit('open-source', edge.source_id)">[{{ edge.source_id }}] 查看来源原文</a>
        <p v-else class="muted">此历史关系未提供来源标识。</p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.evidence-graph { margin-top: 28px; color: var(--gray-900); overflow-wrap: anywhere; }
h3 { font-size: 17px; margin: 0 0 12px; }
p { margin: 8px 0 12px; }
.explanation, .muted { color: var(--gray-600); font-size: 13px; }
.filters { display: grid; grid-template-columns: minmax(160px, 2fr) minmax(110px, 1fr) minmax(150px, 1.5fr); gap: 12px; margin-top: 18px; }
label { display: flex; flex-direction: column; min-width: 0; gap: 6px; font-size: 13px; }
input, select { width: 100%; min-width: 0; box-sizing: border-box; padding: 9px 10px; border: 1px solid var(--gray-300); border-radius: 6px; background: var(--gray-0); color: var(--gray-900); font: inherit; }
.filter-summary { display: flex; gap: 12px; align-items: center; justify-content: space-between; font-size: 13px; margin-top: 8px; }
button { border: 1px solid var(--gray-300); border-radius: 6px; background: var(--gray-0); padding: 5px 10px; color: var(--gray-900); font: inherit; cursor: pointer; white-space: nowrap; }
input:focus-visible, select:focus-visible, button:focus-visible, a:focus-visible { outline: 2px solid var(--main-color); outline-offset: 3px; }
.empty-state { padding: 16px; border: 1px dashed var(--gray-300); border-radius: 8px; background: var(--gray-50); }
.relation { border: 1px solid var(--gray-200); border-radius: 10px; padding: 18px; margin: 12px 0; }
.badges { display: flex; flex-wrap: wrap; gap: 6px; }
.badge { display: inline-block; font-size: 12px; font-weight: 500; padding: 2px 8px; border-radius: 5px; color: var(--main-800); background: var(--main-50); }
.relation-statement { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; }
.relation-arrow { color: var(--gray-600); }
blockquote { margin: 8px 0; padding: 8px 14px; border-left: 3px solid var(--gray-200); white-space: pre-wrap; }
a { color: var(--main-color); text-decoration: underline; font-size: 13px; }
@media (max-width: 700px) { .filters { grid-template-columns: 1fr 1fr; } .search-field { grid-column: 1 / -1; } }
@media (max-width: 450px) { .filters { grid-template-columns: 1fr; } .relation { padding: 12px; } }
</style>
