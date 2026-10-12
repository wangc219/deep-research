<script setup>
defineProps({ coverage: { type: Object, default: null }, sourcePrefix: { type: String, default: 'document-source' } })
defineEmits(['open-source'])
</script>

<template>
  <section v-if="coverage?.candidates?.length" class="evidence-coverage" aria-label="候选资料提及">
    <h3>候选资料提及</h3>
    <p>本次检索提供 {{ coverage.total_sources }} 条资料。下列信息只表示资料中提及了候选名称，不代表功能证据充分、方案更优或已通过实测。</p>
    <ul>
      <li v-for="candidate in coverage.candidates" :key="candidate.name">
        <div class="candidate"><strong>{{ candidate.name }}</strong><span>{{ candidate.source_ids?.length ? `${candidate.source_ids.length} 条资料提及` : '未找到名称提及' }}</span></div>
        <div v-if="candidate.source_ids?.length" class="citations"><a v-for="id in candidate.source_ids" :key="id" :href="`#${sourcePrefix}-${encodeURIComponent(id)}`" @click.prevent="$emit('open-source', id)">[{{ id }}]</a></div>
        <p v-else class="gap">可补充该方案的官方文档或公开检索结果，再比较能力与局限。</p>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.evidence-coverage { margin-top: 22px; border: 1px solid var(--gray-200); border-radius: 10px; padding: 16px; color: var(--gray-900); overflow-wrap: anywhere; }
h3 { font-size: 17px; margin: 0 0 10px; }
p { margin: 8px 0 12px; font-size: 13px; color: var(--gray-600); }
ul { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
li { margin: 0; padding: 12px; border-radius: 8px; background: var(--gray-50); }
.candidate { display: flex; flex-direction: column; gap: 4px; font-size: 14px; }
.candidate span, .gap { font-size: 12px; color: var(--gray-600); }
.citations { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; font-size: 13px; }
a { color: var(--main-color); text-decoration: underline; }
a:focus-visible { outline: 2px solid var(--main-color); outline-offset: 3px; }
@media (max-width: 600px) { ul { grid-template-columns: 1fr; } }
</style>
