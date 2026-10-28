<script setup>
import { computed } from 'vue'
import { BrainCircuit, ChevronDown, Eye, GitCompare, MessageSquare, Star, Trash2, Wrench } from '@lucide/vue'
import CapabilityDeepVersionSwitcher from '@/components/equipment/CapabilityDeepVersionSwitcher.vue'
import {
  capabilityCardKey,
  capabilityComparisonFields,
  capabilityConfidence,
  capabilityDisplayEquipmentForm,
  capabilityDirection,
  capabilityDimensions,
  capabilityPortraitComplete,
  capabilityPortraitModules,
  capabilityTitle,
  capabilityVersionMeta,
  isCapabilityDeepResearch
} from '@/utils/equipmentCapabilities'
import { isTechnologyCabinSection } from '@/utils/equipmentDeepPortraitSections.js'
import { portraitOverview } from '@/utils/portraitOverview.js'

const props = defineProps({
  item: { type: Object, required: true },
  formalItem: { type: Object, default: null },
  deepVersions: { type: Array, default: () => [] },
  favorite: { type: Object, default: null },
  favoritePending: { type: Boolean, default: false },
  feedbackCount: { type: Number, default: 0 },
  versionBusy: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
  surface: {
    type: String,
    default: 'capabilities',
    validator: (value) => ['capabilities', 'report'].includes(value)
  }
})

defineEmits(['feedback', 'view-feedback', 'deep', 'favorite', 'jump', 'view', 'delete-version'])

const title = computed(() => capabilityTitle(props.item))
const direction = computed(() => capabilityDirection(props.item) || capabilityDisplayEquipmentForm(props.item))
const meta = computed(() => capabilityVersionMeta(props.item))
const deepResearch = computed(() => isCapabilityDeepResearch(props.item))
const pendingVerification = computed(() => ['pending', 'pending_verification', 'unverified'].includes(meta.value.status) || props.item.confidence_limited === true)
const modules = computed(() => capabilityPortraitModules(props.item))
const overviewModule = computed(() => modules.value.find((entry) => entry.label === '概述') || null)
const detailModules = computed(() => modules.value.filter((entry) => entry.label !== '概述'))
const overview = computed(() => portraitOverview(overviewModule.value?.text))
const dimensionData = computed(() => capabilityDimensions(props.item))
const favoriteEligible = computed(() => !deepResearch.value && capabilityPortraitComplete(props.item))
const comparisonFields = computed(() => props.formalItem ? capabilityComparisonFields(props.formalItem, props.item) : [])
const reportSurface = computed(() => props.surface === 'report')
const scoreTitle = computed(() => {
  const values = props.item.confidence_components || {}
  const percent = (value) => `${Math.round(Number(value || 0) * 100)}%`
  return `证据贴合 ${percent(values.evidence_fit)} · 前瞻可验证 ${percent(values.foresight)}`
})
</script>

<template>
  <article
    class="capability-sheet"
    :class="{ 'pending-verification': pendingVerification, 'deep-research-capability': deepResearch }"
    :data-card-key="capabilityCardKey(item)"
  >
    <header>
      <div>
        <div class="capability-title-row">
          <div class="capability-identity">
            <span>装备名称</span>
            <h2>{{ title }}<small v-if="meta.version" class="capability-version-label">v{{ meta.version }}</small></h2>
            <details v-if="(direction && direction !== title) || dimensionData.values.length" class="capability-classification">
              <summary>方向与分类</summary>
              <p v-if="direction && direction !== title"><b>装备方向</b>{{ direction }}</p>
              <div v-if="dimensionData.values.length" class="capability-dimension-tags" aria-label="能力分类">
                <span v-for="(value, index) in dimensionData.values" :key="value" :class="{ primary: index === 0 }"><i>{{ index === 0 ? '主' : '辅' }}</i>{{ value }}</span>
              </div>
              <p v-if="dimensionData.basis"><b>分类依据</b>{{ dimensionData.basis }}</p>
            </details>
          </div>
          <span v-if="deepResearch" class="capability-source-badge deep-research-source">深研结果</span>
          <button
            v-if="!reportSurface"
            type="button"
            class="favorite-star"
            :class="{ 'is-favorited': favorite, 'is-pending': favoritePending }"
            :disabled="(!favoriteEligible && !favorite) || favoritePending"
            :aria-pressed="Boolean(favorite)"
            :aria-label="favorite ? `取消收藏：${title}` : `收藏：${title}`"
            :title="!favoriteEligible && !favorite ? '仅完整 S6 能力画像可收藏' : favorite ? '取消收藏' : '收藏能力画像'"
            @click="$emit('favorite', item, !favorite)"
          ><Star :size="17" :fill="favorite ? 'currentColor' : 'none'" /></button>
        </div>
        <div class="capability-card-actions">
          <button v-if="!reportSurface" type="button" :disabled="readOnly" :title="readOnly ? '历史研究任务为只读数据' : ''" @click="$emit('feedback', item)"><MessageSquare :size="13" />针对本卡反馈</button>
          <button type="button" class="deep-followup-button" :disabled="readOnly" :title="readOnly ? '历史研究任务为只读数据' : ''" @click="$emit('deep', item)"><BrainCircuit :size="13" />定向深研 / 追问</button>
          <button v-if="reportSurface" type="button" class="capability-jump-button" @click="$emit('view', item)"><Eye :size="13" />查看完整画像</button>
          <button v-else-if="deepResearch && formalItem" type="button" class="capability-jump-button" @click="$emit('jump', formalItem)"><Eye :size="13" />查看正式原卡</button>
          <button v-if="!reportSurface && deepResearch && item.version_id" type="button" class="capability-version-delete" :disabled="readOnly || versionBusy" :title="readOnly ? '历史研究任务为只读数据' : ''" @click="$emit('delete-version', item)"><Trash2 :size="13" />{{ versionBusy ? '删除中…' : '删除此版本' }}</button>
          <button v-if="!reportSurface" type="button" @click="$emit('view-feedback', item)"><MessageSquare :size="12" />反馈记录 {{ feedbackCount }}</button>
          <span v-if="deepResearch" class="deep-job-chip">{{ meta.statusLabel }} · {{ meta.source || '深研来源' }}</span>
        </div>
      </div>
      <div class="capability-score" :title="scoreTitle">
        <b>{{ capabilityConfidence(item) }}</b>
        <small>{{ pendingVerification ? '综合置信度（待核验）' : '综合置信度' }}</small>
      </div>
    </header>

    <CapabilityDeepVersionSwitcher
      v-if="!reportSurface && !deepResearch"
      :versions="deepVersions"
      @select="$emit('jump', $event)"
    />

    <section v-if="modules.length" class="capability-portrait">
      <small>装备能力画像 · 默认仅展示概述，其余栏目按需展开</small>
      <div class="capability-portrait-cards">
        <article
          v-if="overviewModule"
          class="capability-portrait-card"
        >
          <header>
            <b>{{ overviewModule.label }}</b>
            <button
              type="button"
              class="portrait-dive-button"
              :disabled="readOnly"
              :title="readOnly ? '历史研究任务为只读数据' : ''"
              :aria-label="`深挖${title}的${overviewModule.label}`"
              @click="$emit('deep', item, overviewModule)"
            >
              <BrainCircuit :size="12" />
              深挖本栏
            </button>
          </header>
          <div class="portrait-overview">
            <ul v-if="overview.paragraphs.length" class="overview-points">
              <li v-for="(paragraph, index) in overview.paragraphs" :key="index">{{ paragraph }}</li>
            </ul>
            <dl v-if="overview.fields.length" class="overview-fields">
              <div v-for="field in overview.fields" :key="field.label">
                <dt>{{ field.label }}</dt><dd :class="{ 'is-missing': !field.text }">{{ field.text || '原文未单独说明' }}</dd>
              </div>
            </dl>
            <small v-else class="overview-legacy-note">历史概述按原文分条展示，尚未标注背景、思路、效果与创新。</small>
          </div>
        </article>

        <details v-if="detailModules.length" class="capability-portrait-secondary">
          <summary>
            <span class="portrait-secondary-copy">
              <strong><span class="secondary-closed">展开其余 {{ detailModules.length }} 个栏目</span><span class="secondary-open">收起其余栏目</span></strong>
              <small>技术实现、作战流程、能力效果与制胜机理</small>
            </span>
            <span class="portrait-secondary-action"><span class="secondary-closed">查看详情</span><span class="secondary-open">收起</span><ChevronDown :size="16" /></span>
          </summary>
          <div class="capability-portrait-secondary-cards">
            <article
              v-for="entry in detailModules"
              :key="`${capabilityCardKey(item)}-${entry.label}`"
              class="capability-portrait-card"
              :class="{ 'technology-cabin-card': isTechnologyCabinSection(entry.label) }"
            >
              <header>
                <b>{{ entry.label }}</b>
                <button
                  type="button"
                  class="portrait-dive-button"
                  :class="{ 'technology-cabin-entry': isTechnologyCabinSection(entry.label) }"
                  :disabled="readOnly"
                  :title="readOnly ? '历史研究任务为只读数据' : ''"
                  :aria-label="isTechnologyCabinSection(entry.label) ? `进入${title}的技术攻关舱` : `深挖${title}的${entry.label}`"
                  @click="$emit('deep', item, entry)"
                >
                  <Wrench v-if="isTechnologyCabinSection(entry.label)" :size="12" />
                  <BrainCircuit v-else :size="12" />
                  {{ isTechnologyCabinSection(entry.label) ? '技术攻关舱' : '深挖本栏' }}
                </button>
              </header>
              <p>{{ entry.text }}</p>
              <slot v-if="isTechnologyCabinSection(entry.label)" name="technology-solution" />
            </article>
          </div>
        </details>
      </div>
    </section>
    <div v-else class="capability-legacy-note">等待 S6 单卡成稿</div>

    <section v-if="!reportSurface && deepResearch && formalItem" class="deep-research-comparison">
      <header><div><GitCompare :size="15" /><span><b>与正式原卡对比</b><small>正式卡保持不变，以下仅展示本次深研形成的独立版本差异。</small></span></div><button type="button" class="capability-jump-button" @click="$emit('jump', formalItem)"><Eye :size="13" />定位正式原卡</button></header>
      <div class="deep-research-comparison-grid">
        <div><strong>正式原卡</strong><dl v-for="field in comparisonFields" :key="`formal-${field[0]}`"><dt>{{ field[0] }}</dt><dd>{{ field[1] }}</dd></dl></div>
        <div><strong>当前深研卡片</strong><dl v-for="field in comparisonFields" :key="`deep-${field[0]}`"><dt>{{ field[0] }}</dt><dd>{{ field[2] }}</dd></dl></div>
      </div>
    </section>
  </article>
</template>

<style scoped>
.capability-classification > summary {
  width: fit-content;
  color: var(--main-700);
  cursor: pointer;
  font-size: 12px;
  line-height: 1.7;
}
.capability-classification > summary:focus-visible { outline: 2px solid var(--main-400); outline-offset: 4px; }
.capability-classification { margin-top: 4px; }
.capability-classification > p { margin-top: 8px; line-height: 1.7; overflow-wrap: anywhere; }
.capability-classification > p b { margin-right: 8px; color: var(--gray-600); }
.capability-classification .capability-dimension-tags { margin-top: 8px; }
.portrait-overview { margin-top: 12px; color: var(--gray-800); font-size: 14px; line-height: 1.8; overflow-wrap: anywhere; }
.overview-points { margin: 0; padding-left: 22px; }
.overview-points li + li { margin-top: 8px; }
.overview-fields { display: grid; gap: 10px; margin: 0; }
.overview-points + .overview-fields { margin-top: 12px; }
.overview-fields > div { display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 12px; }
.overview-fields dt { color: var(--main-700); font-weight: 650; }
.overview-fields dd { margin: 0; white-space: pre-wrap; }
.overview-fields .is-missing,
.overview-legacy-note { color: var(--gray-500); }
.overview-legacy-note { display: block; margin-top: 10px; font-size: 11px; }
.capability-portrait-secondary {
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--main-300) 58%, var(--gray-100));
  border-radius: 10px;
  background: color-mix(in srgb, var(--gray-0) 82%, var(--main-50));
}
.capability-portrait-secondary > summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  min-height: 58px;
  padding: 11px 14px;
  color: var(--gray-800);
  cursor: pointer;
  list-style: none;
}
.capability-portrait-secondary > summary::-webkit-details-marker { display: none; }
.capability-portrait-secondary > summary:hover { background: color-mix(in srgb, var(--main-50) 74%, transparent); }
.capability-portrait-secondary > summary:focus-visible { outline: 2px solid var(--main-400); outline-offset: -3px; }
.portrait-secondary-copy { display: grid; min-width: 0; gap: 3px; }
.portrait-secondary-copy strong { color: var(--gray-900); font-size: 13px; }
.portrait-secondary-copy small { overflow: hidden; color: var(--gray-500); font-size: 11px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.portrait-secondary-action { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 6px; color: var(--main-700); font-size: 11px; font-weight: 650; }
.secondary-open,
.capability-portrait-secondary[open] .secondary-closed { display: none; }
.capability-portrait-secondary[open] .secondary-open { display: inline; }
.capability-portrait-secondary[open] > summary svg { transform: rotate(180deg); }
.capability-portrait-secondary-cards { display: grid; gap: 10px; padding: 12px; border-top: 1px solid color-mix(in srgb, var(--main-300) 42%, var(--gray-100)); }
.capability-portrait-secondary-cards :deep(.technology-solution) { margin: 14px 0 0; }
@media (max-width: 640px) {
  .overview-fields > div { grid-template-columns: 1fr; gap: 2px; }
  .portrait-overview { font-size: 13px; }
  .portrait-secondary-copy small { display: none; }
}
@media print {
  .capability-portrait-secondary > summary { display: none; }
  .capability-portrait-secondary:not([open]) > .capability-portrait-secondary-cards { display: grid; }
}

.capability-portrait-card > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.portrait-dive-button {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 4px;
  padding: 3px 7px;
  border: 1px solid var(--main-200);
  border-radius: 999px;
  background: var(--main-50);
  color: var(--main-700);
  cursor: pointer;
  font-size: 10px;
  line-height: 1.4;
}

.portrait-dive-button:hover,
.portrait-dive-button:focus-visible {
  border-color: var(--main-400);
  background: var(--main-100);
}

.capability-portrait-card.technology-cabin-card {
  border-color: color-mix(in srgb, var(--main-300) 72%, var(--gray-100));
  background: linear-gradient(145deg, var(--gray-0), var(--main-50));
}

.portrait-dive-button.technology-cabin-entry {
  border-color: var(--main-400);
  background: var(--main-color);
  color: white;
  font-weight: 650;
}

.portrait-dive-button.technology-cabin-entry:hover,
.portrait-dive-button.technology-cabin-entry:focus-visible {
  border-color: var(--main-600);
  background: var(--main-700);
}
</style>
