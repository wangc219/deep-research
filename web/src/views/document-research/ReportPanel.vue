<script setup>
import { computed, ref } from 'vue'
import EvidenceSources from './EvidenceSources.vue'
import RetrievalStatus from './RetrievalStatus.vue'
import EvidenceGraph from './EvidenceGraph.vue'
import EvidenceCoverage from './EvidenceCoverage.vue'
import { citedSourceIds } from './evidencePresentation'
const props = defineProps({ report: { type: Object, required: true } })
const sources = ref(null)
const isAnswer = computed(() => props.report.mode === 'answer')
const citedIds = computed(() => citedSourceIds(props.report))
function openSource(id) { sources.value?.openSource(id) }
</script>

<template>
  <article class="report" :aria-label="isAnswer ? '证据问答' : '文档解析研究报告'">
    <div class="report-heading"><h2>{{ isAnswer ? '有据回答' : '研究方案' }}</h2><span class="badge">未实测 · 待验证</span></div>
    <p v-if="!isAnswer">以下为建议方案、实验步骤与拟定验收指标，未运行候选解析器实验。</p>
    <p v-if="!isAnswer" class="summary">{{ report.summary }}</p>
    <section v-if="report.warnings?.length" class="notice"><h3>本次限制</h3><ul><li v-for="(item, i) in report.warnings" :key="i">{{ item }}</li></ul></section>

    <RetrievalStatus :items="report.retrieval_status || []" />
    <EvidenceCoverage :coverage="report.evidence_coverage" @open-source="openSource" />
    <section v-if="isAnswer" aria-label="回答与原文">
      <p v-if="!report.answer?.length">当前证据不足，暂时无法给出有依据的回答。请查看下方证据缺口。</p>
      <div v-for="(item, i) in report.answer" :key="i" class="comparison"><p>{{ item.text }}</p><blockquote>{{ item.quote }}</blockquote><a :href="`#document-source-${encodeURIComponent(item.source_id)}`" @click.prevent="openSource(item.source_id)">[{{ item.source_id }}] 查看来源原文</a></div>
    </section>
    <template v-if="!isAnswer">
    <section><h3>方案比较</h3>
      <p v-if="!report.comparisons?.length">证据不足，暂未形成可比较方案。</p>
      <div v-for="(candidate, i) in report.comparisons" :key="i" class="comparison">
        <h4>{{ candidate.name }}</h4><p>{{ candidate.approach }}</p>
        <div class="pros-cons"><div><strong>优点</strong><ul><li v-for="(item, n) in candidate.pros" :key="n">{{ item }}</li></ul></div><div><strong>局限</strong><ul><li v-for="(item, n) in candidate.cons" :key="n">{{ item }}</li></ul></div></div>
        <div class="citations">依据：<a v-for="id in candidate.source_ids" :key="id" :href="`#document-source-${encodeURIComponent(id)}`" @click.prevent="openSource(id)">[{{ id }}]</a><span v-if="!candidate.source_ids?.length">无引用，待验证</span></div>
      </div>
    </section>

    <section><h3>实验步骤与验收指标</h3>
      <div v-for="(experiment, i) in report.experiments" :key="i" class="comparison">
        <h4>{{ i + 1 }}. {{ experiment.name }}</h4><ol><li v-for="(step, n) in experiment.steps" :key="n">{{ step }}</li></ol>
        <strong>拟定指标</strong><ul><li v-for="(metric, n) in experiment.metrics" :key="n">{{ metric }}</li></ul>
        <p><strong>验收条件：</strong>{{ experiment.acceptance }}</p>
        <div class="citations">依据：<a v-for="id in experiment.source_ids" :key="id" :href="`#document-source-${encodeURIComponent(id)}`" @click.prevent="openSource(id)">[{{ id }}]</a><span v-if="!experiment.source_ids?.length">建议实验，待验证</span></div>
      </div>
    </section>

    <section class="recommendation"><h3>推荐理由</h3><p>{{ report.recommendation?.text || '证据不足，暂无确定推荐。' }}</p>
      <div class="citations"><a v-for="id in report.recommendation?.source_ids" :key="id" :href="`#document-source-${encodeURIComponent(id)}`" @click.prevent="openSource(id)">[{{ id }}]</a></div>
    </section>
    </template>
    <section v-if="report.assumptions?.length"><h3>假设</h3><ul><li v-for="(item, i) in report.assumptions" :key="i">{{ item }}</li></ul></section>
    <section v-if="report.gaps?.length"><h3>证据缺口与待验证项</h3><ul><li v-for="(item, i) in report.gaps" :key="i">{{ item }}</li></ul></section>

    <EvidenceGraph :graph="report.graph || []" :sources="report.sources || []" :removed-count="report.graph_removed_count || 0" @open-source="openSource" />

    <section><h3>本次提供给模型的来源</h3><p>以下来源曾提供给模型；标记说明哪些被回答、方案或证据关系实际引用。</p><p v-if="!report.sources?.length">没有可用来源。</p>
      <EvidenceSources ref="sources" :sources="report.sources || []" :cited-ids="citedIds" />
    </section>
  </article>
</template>

<style scoped>
.report { color: var(--gray-900); line-height: 1.7; overflow-wrap: anywhere; }
.report-heading { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
h2 { font-size: 22px; margin: 0; } h3 { font-size: 17px; margin: 0 0 12px; } h4 { font-size: 16px; margin: 0 0 8px; }
p { margin: 8px 0 12px; } section { margin-top: 28px; } ul, ol { padding-left: 24px; } li { margin: 5px 0; }
.summary { white-space: pre-wrap; } .comparison, .relation { border: 1px solid var(--gray-200); border-radius: 10px; padding: 18px; margin: 12px 0; }
.pros-cons { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.badge { display: inline-block; font-size: 12px; font-weight: 500; padding: 2px 8px; border-radius: 5px; color: var(--main-800); background: var(--main-50); }
.notice, .recommendation { padding: 18px; background: var(--main-20); border-left: 3px solid var(--main-color); border-radius: 6px; }
.citations { display: flex; flex-wrap: wrap; gap: 6px; font-size: 13px; } a { color: var(--main-color); text-decoration: underline; }
blockquote { margin: 8px 0; padding: 8px 14px; border-left: 3px solid var(--gray-200); white-space: pre-wrap; }
.source { border-top: 1px solid var(--gray-200); padding: 16px 0; scroll-margin-top: 90px; } summary { cursor: pointer; }
pre { margin: 12px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; max-height: 320px; overflow-y: auto; background: var(--gray-50); padding: 12px; border-radius: 6px; }
.muted { color: var(--gray-600); font-size: 13px; }
@media (max-width: 600px) { .pros-cons { grid-template-columns: 1fr; gap: 4px; } .comparison, .relation { padding: 12px; } }
</style>
