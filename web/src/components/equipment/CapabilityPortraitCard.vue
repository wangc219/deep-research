<script setup>
import { computed } from 'vue'
import { BrainCircuit, Eye, GitCompare, MessageSquare, Star, Trash2, Wrench } from '@lucide/vue'
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

defineEmits(['feedback', 'deep', 'favorite', 'jump', 'view', 'delete-version'])

const title = computed(() => capabilityTitle(props.item))
const direction = computed(() => capabilityDirection(props.item) || capabilityDisplayEquipmentForm(props.item))
const meta = computed(() => capabilityVersionMeta(props.item))
const deepResearch = computed(() => isCapabilityDeepResearch(props.item))
const pendingVerification = computed(() => ['pending', 'pending_verification', 'unverified'].includes(meta.value.status) || props.item.confidence_limited === true)
const modules = computed(() => capabilityPortraitModules(props.item))
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
            <p v-if="direction"><b>装备方向</b>{{ direction }}</p>
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
          <span v-if="!reportSurface && feedbackCount"><MessageSquare :size="12" /> {{ feedbackCount }} 条反馈</span>
          <span v-if="deepResearch" class="deep-job-chip">{{ meta.statusLabel }} · {{ meta.source || '深研来源' }}</span>
        </div>
      </div>
      <div class="capability-score" :title="scoreTitle">
        <b>{{ capabilityConfidence(item) }}</b>
        <small>{{ pendingVerification ? '综合置信度（待核验）' : '综合置信度' }}</small>
      </div>
    </header>

    <section v-if="dimensionData.values.length" class="capability-dimensions">
      <div class="capability-dimensions-head"><b>武器维度</b><span>按当前装备的主要战果与作战节点匹配，维度不限制 S6 继续推演新的能力关系。</span></div>
      <div class="capability-dimension-tags"><span v-for="(value, index) in dimensionData.values" :key="value" :class="{ primary: index === 0 }"><i>{{ index === 0 ? '主' : '辅' }}</i>{{ value }}</span></div>
      <p v-if="dimensionData.basis">{{ dimensionData.basis }}</p>
    </section>

    <CapabilityDeepVersionSwitcher
      v-if="!reportSurface && !deepResearch"
      :versions="deepVersions"
      @select="$emit('jump', $event)"
    />

    <section v-if="modules.length" class="capability-portrait">
      <small>装备能力画像 · S6 五栏作战论证 · 可直接深挖任一栏</small>
      <div class="capability-portrait-cards">
        <article
          v-for="entry in modules"
          :key="entry.label"
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
        </article>
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
