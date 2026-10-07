<script setup>
import { computed, ref, watch } from 'vue'
import {
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Clock3,
  GitCompare,
  History,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Trash2
} from '@lucide/vue'
import { equipmentApi } from '@/apis/equipment_api'
import { capabilityTitle } from '@/utils/equipmentCapabilities.js'
import {
  buildSessionCandidateVersionCards,
  candidateVersionId,
  candidateVersionStatus,
  candidateVersionStatusLabel
} from '@/utils/equipmentDeepCandidateVersions.js'
import { formatFullDateTime } from '@/utils/time'

const props = defineProps({
  runId: { type: String, default: '' },
  sessionId: { type: String, default: '' },
  versions: { type: Array, default: null },
  autoLoad: { type: Boolean, default: true },
  readOnly: { type: Boolean, default: false },
  showEmpty: { type: Boolean, default: true },
  confirmMutations: { type: Boolean, default: true }
})

const emit = defineEmits(['loaded', 'changed', 'error', 'open-portrait'])

const ledger = ref([])
const loading = ref(false)
const error = ref('')
const busyVersionId = ref('')
const expandedPortraits = ref(new Set())

const externallyManaged = computed(() => Array.isArray(props.versions))
const cards = computed(() =>
  buildSessionCandidateVersionCards(ledger.value, String(props.sessionId || '').trim())
)

const setLedger = (items) => {
  ledger.value = Array.isArray(items) ? [...items] : []
}

watch(
  () => props.versions,
  (items) => {
    if (Array.isArray(items)) setLedger(items)
  },
  { deep: true, immediate: true }
)

const loadVersions = async ({ force = false } = {}) => {
  const runId = String(props.runId || '').trim()
  if (!runId) {
    if (!externallyManaged.value) setLedger([])
    return false
  }
  if (externallyManaged.value && !force) return true

  loading.value = true
  error.value = ''
  try {
    const result = await equipmentApi.listCapabilityVersions(runId)
    setLedger(result?.versions)
    emit('loaded', {
      runId,
      sessionId: props.sessionId,
      versions: [...ledger.value],
      candidates: [...cards.value]
    })
    return true
  } catch (reason) {
    error.value = reason?.message || '本会话候选能力卡读取失败'
    emit('error', reason)
    return false
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.runId, props.sessionId, props.autoLoad],
  ([runId], previous = []) => {
    if (runId !== previous[0]) {
      expandedPortraits.value = new Set()
      if (!externallyManaged.value) setLedger([])
    }
    if (props.autoLoad && !externallyManaged.value) void loadVersions()
  },
  { immediate: true }
)

const replaceVersion = (nextVersion) => {
  const nextId = candidateVersionId(nextVersion)
  if (!nextId) return
  const index = ledger.value.findIndex((item) => candidateVersionId(item) === nextId)
  if (index < 0) {
    ledger.value = [nextVersion, ...ledger.value]
    return
  }
  ledger.value = ledger.value.map((item, itemIndex) =>
    itemIndex === index ? nextVersion : item
  )
}

const mutationConfirmation = (card, action) => {
  if (!props.confirmMutations || typeof window === 'undefined') return true
  const name = capabilityTitle(card.version)
  const version = card.version.version_no ? `v${card.version.version_no}` : '当前版本'
  if (action === 'delete') {
    return window.confirm(
      `确定隐藏“${name} · ${version}”吗？\n\n该版本不会出现在正式能力画像中，之后仍可恢复。`
    )
  }
  if (action === 'purge') {
    return window.confirm(
      `确定永久删除“${name} · ${version}”吗？\n\n此操作不可恢复，正式 S6 基线不受影响。`
    )
  }
  return true
}

const mutateVersion = async (card, action) => {
  const versionId = candidateVersionId(card.version)
  if (
    !props.runId ||
    !versionId ||
    props.readOnly ||
    busyVersionId.value ||
    candidateVersionStatus(card.version) === 'formal' ||
    !mutationConfirmation(card, action)
  ) {
    return
  }

  busyVersionId.value = versionId
  error.value = ''
  try {
    let result
    if (action === 'verify') {
      result = await equipmentApi.verifyCapabilityVersion(props.runId, versionId, 'verified')
    } else if (action === 'delete') {
      result = await equipmentApi.deleteCapabilityVersion(props.runId, versionId)
    } else if (action === 'restore') {
      result = await equipmentApi.restoreCapabilityVersion(props.runId, versionId)
    } else if (action === 'purge') {
      result = await equipmentApi.purgeCapabilityVersion(props.runId, versionId)
    } else {
      return
    }

    if (action === 'purge' || result?.deleted === true) {
      ledger.value = ledger.value.filter((item) => candidateVersionId(item) !== versionId)
    } else if (result?.version) {
      replaceVersion(result.version)
    }

    await loadVersions({ force: true })
    emit('changed', {
      action,
      runId: props.runId,
      sessionId: props.sessionId,
      versionId,
      response: result,
      versions: [...ledger.value],
      candidates: [...cards.value]
    })
  } catch (reason) {
    error.value = reason?.message || '候选能力卡版本操作失败'
    emit('error', reason)
  } finally {
    busyVersionId.value = ''
  }
}

const isExpanded = (card) => expandedPortraits.value.has(card.id)
const togglePortrait = (card) => {
  const next = new Set(expandedPortraits.value)
  if (next.has(card.id)) next.delete(card.id)
  else next.add(card.id)
  expandedPortraits.value = next
  emit('open-portrait', {
    ...card,
    expanded: next.has(card.id)
  })
}

const displayTime = (value) => (value ? formatFullDateTime(value) : '历史导入版本')
const isBusy = (card) => busyVersionId.value === card.id

defineExpose({
  refresh: () => loadVersions({ force: true })
})
</script>

<template>
  <section class="deep-candidate-versions" aria-label="本会话候选能力卡">
    <header class="candidate-section-header">
      <div>
        <span class="candidate-section-icon"><Sparkles :size="15" /></span>
        <span>
          <b>本会话候选能力卡</b>
          <small>五栏草案独立成版，正式 S6 基线保持不变</small>
        </span>
      </div>
      <div class="candidate-section-summary">
        <em>{{ cards.length }} 个版本</em>
        <button
          v-if="runId"
          type="button"
          class="candidate-refresh"
          :disabled="loading || Boolean(busyVersionId)"
          aria-label="刷新候选能力卡版本"
          @click="loadVersions({ force: true })"
        >
          <RefreshCw :size="13" :class="{ spin: loading }" />刷新
        </button>
      </div>
    </header>

    <p v-if="error" class="candidate-inline-error" role="alert">
      <CircleAlert :size="14" />{{ error }}
    </p>

    <div v-if="loading && !cards.length" class="candidate-state" role="status">
      <RefreshCw :size="17" class="spin" />正在读取本会话能力卡版本…
    </div>

    <div v-else-if="!cards.length && showEmpty" class="candidate-state empty">
      <Sparkles :size="18" />
      <span><b>本会话尚未形成候选能力卡</b><small>在对话中选择“形成能力卡”后，五栏草案会显示在这里。</small></span>
    </div>

    <div v-else class="candidate-version-list">
      <article
        v-for="card in cards"
        :key="card.id"
        class="candidate-version-card"
        :class="[
          `status-${candidateVersionStatus(card.version)}`,
          { expanded: isExpanded(card), incomplete: card.completedModules < 5 }
        ]"
      >
        <header class="candidate-card-header">
          <span class="candidate-card-icon"><Sparkles :size="15" /></span>
          <div>
            <b>{{ capabilityTitle(card.version) }}</b>
            <small>
              {{ card.completedModules === 5 ? '五栏能力画像已形成' : `能力画像草稿 · ${card.completedModules}/5 栏` }}
              <template v-if="card.version.version_no"> · v{{ card.version.version_no }}</template>
            </small>
          </div>
          <span
            class="candidate-status"
            :class="candidateVersionStatus(card.version)"
          >
            <CheckCircle2
              v-if="['verified', 'formal'].includes(candidateVersionStatus(card.version))"
              :size="13"
            />
            <CircleAlert
              v-else-if="['rejected', 'rolled_back', 'deleted', 'failed', 'blocked'].includes(candidateVersionStatus(card.version))"
              :size="13"
            />
            <Clock3 v-else :size="13" />
            {{ candidateVersionStatusLabel(card.version.status) }}
          </span>
        </header>

        <button
          type="button"
          class="candidate-portrait-launch"
          :aria-expanded="isExpanded(card)"
          @click="togglePortrait(card)"
        >
          <span>
            <b>{{ card.completedModules === 5 ? '五栏能力画像' : '五栏能力画像草稿' }}</b>
            <small>{{ card.completedModules }}/5 栏已就绪 · {{ isExpanded(card) ? '收起完整内容' : '展开完整内容' }}</small>
          </span>
          <ChevronDown :size="15" />
        </button>

        <div class="candidate-portrait-preview">
          <article
            v-for="module in card.modules"
            :key="module.label"
            :class="{ missing: !module.complete }"
          >
            <b>{{ module.label }}</b>
            <p :title="module.text">{{ module.text || '待补全' }}</p>
          </article>
        </div>

        <div class="candidate-version-meta">
          <span class="candidate-version-number">v{{ card.version.version_no || '?' }}</span>
          <span
            class="candidate-version-status"
            :class="candidateVersionStatus(card.version)"
          >{{ candidateVersionStatusLabel(card.version.status) }}</span>
          <span>{{ displayTime(card.version.created_at) }}</span>
          <span v-if="card.version.source">来源：{{ card.version.source }}</span>
          <span v-if="card.version.evidence_refs.length">证据 {{ card.version.evidence_refs.length }} 条</span>
        </div>

        <details v-if="card.baseline" class="candidate-baseline-diff">
          <summary>
            <span><GitCompare :size="14" /><b>与正式基线差异</b></span>
            <em>{{ card.diff.length ? `${card.diff.length} 项变化` : '可比字段一致' }}</em>
          </summary>
          <div v-if="card.diff.length" class="candidate-diff-list">
            <article v-for="entry in card.diff" :key="entry.label">
              <b>{{ entry.label }}</b>
              <div><span>正式基线</span><p>{{ entry.before }}</p></div>
              <div><span>当前候选</span><p>{{ entry.after }}</p></div>
            </article>
          </div>
          <p v-else class="candidate-no-diff">
            当前可比字段与“{{ capabilityTitle(card.baseline) }}”正式基线一致。
          </p>
        </details>
        <p v-else class="candidate-baseline-missing">
          <GitCompare :size="13" />未匹配到同谱系正式基线；本候选仍作为独立版本保留。
        </p>

        <footer class="candidate-card-actions">
          <span v-if="readOnly" class="candidate-read-only">
            <ShieldCheck :size="13" />只读版本
          </span>
          <template v-else-if="candidateVersionStatus(card.version) === 'deleted'">
            <button
              type="button"
              class="restore"
              :disabled="isBusy(card)"
              @click="mutateVersion(card, 'restore')"
            >
              <RefreshCw v-if="isBusy(card)" :size="13" class="spin" />
              <History v-else :size="13" />恢复版本
            </button>
            <button
              type="button"
              class="purge"
              :disabled="isBusy(card)"
              @click="mutateVersion(card, 'purge')"
            >
              <Trash2 :size="13" />永久删除
            </button>
          </template>
          <template v-else>
            <button
              v-if="candidateVersionStatus(card.version) !== 'verified'"
              type="button"
              class="verify"
              :disabled="isBusy(card)"
              title="将该版本标记为已核验"
              @click="mutateVersion(card, 'verify')"
            >
              <RefreshCw v-if="isBusy(card)" :size="13" class="spin" />
              <CheckCircle2 v-else :size="13" />核验通过
            </button>
            <span v-else class="candidate-verified"><CheckCircle2 :size="13" />已完成核验</span>
            <button
              type="button"
              class="delete"
              :disabled="isBusy(card)"
              @click="mutateVersion(card, 'delete')"
            >
              <Trash2 :size="13" />{{ isBusy(card) ? '处理中…' : '隐藏版本' }}
            </button>
          </template>
        </footer>
      </article>
    </div>
  </section>
</template>

<style scoped>
.deep-candidate-versions {
  --candidate-bg: var(--color-bg-container, #fff);
  --candidate-bg-soft: #f8f9fd;
  --candidate-border: #dfe4f1;
  --candidate-border-soft: #e7eaf3;
  --candidate-text: var(--color-text, #33405b);
  --candidate-muted: var(--color-text-secondary, #7c879d);
  width: 100%;
  margin: 18px 0 0;
  padding-top: 10px;
  border-top: 1px solid var(--candidate-border-soft);
  color: var(--candidate-text);
  font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
}

.candidate-section-header,
.candidate-section-header > div,
.candidate-section-summary,
.candidate-card-header,
.candidate-status,
.candidate-version-meta,
.candidate-card-actions,
.candidate-baseline-diff summary,
.candidate-baseline-diff summary > span,
.candidate-baseline-missing,
.candidate-inline-error,
.candidate-read-only,
.candidate-verified {
  display: flex;
  align-items: center;
}

.candidate-section-header {
  justify-content: space-between;
  gap: 12px;
  padding: 0 0 9px;
}

.candidate-section-header > div { gap: 7px; }
.candidate-section-header > div > span:not(.candidate-section-icon) { display: grid; gap: 2px; }
.candidate-section-header b { color: var(--candidate-text); font-size: 12px; }
.candidate-section-header small { color: var(--candidate-muted); font-size: 10px; }

.candidate-section-icon,
.candidate-card-icon {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #eeedfe;
  color: #615ee5;
}

.candidate-section-icon { width: 28px; height: 28px; }
.candidate-card-icon { width: 30px; height: 30px; }
.candidate-section-summary { gap: 8px; }
.candidate-section-summary em { color: #919aac; font-size: 10px; font-style: normal; }

.candidate-refresh,
.candidate-card-actions button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-height: 28px;
  padding: 0 9px;
  border: 1px solid #d7dcef;
  border-radius: 7px;
  background: var(--candidate-bg);
  color: #5653c8;
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}

.candidate-refresh:disabled,
.candidate-card-actions button:disabled { cursor: wait; opacity: .58; }

.candidate-inline-error {
  gap: 6px;
  margin: 0 0 8px;
  padding: 8px 10px;
  border: 1px solid #edcacc;
  border-radius: 8px;
  background: #fff5f5;
  color: #ad5965;
  font-size: 10px;
}

.candidate-state {
  display: flex;
  min-height: 76px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px dashed var(--candidate-border);
  border-radius: 11px;
  color: var(--candidate-muted);
  font-size: 11px;
}

.candidate-state.empty span { display: grid; gap: 3px; }
.candidate-state.empty b { color: var(--candidate-text); font-size: 11px; }
.candidate-state.empty small { font-size: 10px; }
.candidate-version-list { display: grid; gap: 9px; }

.candidate-version-card {
  padding: 12px;
  border: 1px solid var(--candidate-border);
  border-radius: 12px;
  background: var(--candidate-bg);
  box-shadow: 0 4px 15px rgba(48, 62, 105, .035);
}

.candidate-version-card.status-verified { border-color: #c5e0d1; background: #fbfffc; }
.candidate-version-card.status-deleted { border-style: dashed; background: var(--candidate-bg-soft); }
.candidate-version-card.status-rejected,
.candidate-version-card.status-rolled_back { border-color: #edcacc; }

.candidate-card-header { gap: 9px; }
.candidate-card-header > div { min-width: 0; flex: 1; }
.candidate-card-header > div > b,
.candidate-card-header > div > small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.candidate-card-header > div > b { color: var(--candidate-text); font-size: 12px; }
.candidate-card-header > div > small { margin-top: 3px; color: var(--candidate-muted); font-size: 9px; }

.candidate-status {
  flex: 0 0 auto;
  gap: 4px;
  color: #777f96;
  font-size: 9px;
  white-space: nowrap;
}
.candidate-status.verified,
.candidate-status.formal { color: #35825c; }
.candidate-status.rejected,
.candidate-status.rolled_back,
.candidate-status.deleted,
.candidate-status.failed,
.candidate-status.blocked { color: #ad5965; }

.candidate-portrait-launch {
  display: flex;
  width: 100%;
  min-height: 48px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 10px 0 8px;
  padding: 9px 11px;
  border: 1px solid #d8dcf6;
  border-radius: 11px;
  background: linear-gradient(120deg, #f7f8ff, #f3f7ff);
  color: #514ec8;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.candidate-portrait-launch > span { display: grid; min-width: 0; gap: 3px; }
.candidate-portrait-launch b { color: #323f5d; font-size: 11px; }
.candidate-portrait-launch small { color: #6d7893; font-size: 9px; }
.candidate-portrait-launch svg { flex: 0 0 auto; transition: transform .16s ease; }
.candidate-version-card.expanded .candidate-portrait-launch svg { transform: rotate(180deg); }

.candidate-portrait-preview {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 7px;
}
.candidate-portrait-preview > article {
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid #e2e7f4;
  border-radius: 10px;
  background: rgba(248, 250, 255, .82);
}
.candidate-portrait-preview > article.missing { border-style: dashed; background: transparent; }
.candidate-portrait-preview b { display: block; color: #5553bf; font-size: 10px; line-height: 1.4; }
.candidate-portrait-preview p {
  display: -webkit-box;
  overflow: hidden;
  margin: 5px 0 0;
  color: #68748d;
  font-size: 10px;
  line-height: 1.55;
  white-space: pre-wrap;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}
.candidate-portrait-preview > article.missing p { color: #a0a8b8; }
.candidate-version-card.expanded .candidate-portrait-preview p {
  display: block;
  overflow: visible;
  -webkit-line-clamp: unset;
}

.candidate-version-meta {
  flex-wrap: wrap;
  gap: 5px;
  margin: 9px 0 8px;
  color: #8590a5;
  font-size: 9px;
}
.candidate-version-meta > span {
  display: inline-flex;
  min-height: 20px;
  align-items: center;
  padding: 0 6px;
  border: 1px solid #e1e5ef;
  border-radius: 999px;
  background: #fafbfe;
}
.candidate-version-meta .candidate-version-number { border-color: #d7daf3; color: #5d5adf; font-weight: 700; }
.candidate-version-meta .candidate-version-status { border-color: #d6daf6; background: #f4f4ff; color: #5d5adf; }
.candidate-version-meta .candidate-version-status.verified,
.candidate-version-meta .candidate-version-status.formal { border-color: #c5e1d2; background: #f1fbf5; color: #36815c; }
.candidate-version-meta .candidate-version-status.rejected,
.candidate-version-meta .candidate-version-status.rolled_back,
.candidate-version-meta .candidate-version-status.deleted { border-color: #edcacc; background: #fff5f5; color: #ad5965; }

.candidate-baseline-diff {
  margin-top: 8px;
  border: 1px solid #e1e5f1;
  border-radius: 9px;
  background: var(--candidate-bg-soft);
}
.candidate-baseline-diff summary {
  justify-content: space-between;
  gap: 10px;
  min-height: 34px;
  padding: 0 10px;
  color: #5c5ac2;
  font-size: 10px;
  cursor: pointer;
  list-style: none;
}
.candidate-baseline-diff summary::-webkit-details-marker { display: none; }
.candidate-baseline-diff summary > span { gap: 5px; }
.candidate-baseline-diff summary em { color: #8b94a7; font-size: 9px; font-style: normal; }
.candidate-diff-list { display: grid; gap: 7px; padding: 0 9px 9px; }
.candidate-diff-list > article {
  display: grid;
  grid-template-columns: 100px minmax(0, 1fr) minmax(0, 1fr);
  gap: 7px;
  padding: 8px;
  border: 1px solid #e5e8f1;
  border-radius: 8px;
  background: var(--candidate-bg);
}
.candidate-diff-list > article > b { align-self: start; color: #4d5871; font-size: 10px; }
.candidate-diff-list > article > div { min-width: 0; }
.candidate-diff-list span { color: #919aac; font-size: 9px; }
.candidate-diff-list p { margin: 3px 0 0; color: #606c84; font-size: 10px; line-height: 1.5; white-space: pre-wrap; }
.candidate-no-diff { margin: 0; padding: 0 10px 10px; color: #748198; font-size: 10px; }
.candidate-baseline-missing { gap: 5px; margin: 8px 0 0; color: #919aac; font-size: 9px; }

.candidate-card-actions {
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 10px;
  padding-top: 9px;
  border-top: 1px solid #edf0f5;
}
.candidate-card-actions .verify { border-color: #b8dcc8; background: #f4fbf7; color: #347959; }
.candidate-card-actions .restore { border-color: #b8dcc8; background: #f4fbf7; color: #347959; }
.candidate-card-actions .delete,
.candidate-card-actions .purge { border-color: #efced1; background: #fff8f8; color: #ad5965; }
.candidate-read-only,
.candidate-verified { gap: 5px; min-height: 28px; color: #56806a; font-size: 10px; }
.candidate-read-only { color: #7d8799; }

.spin { animation: candidate-spin .9s linear infinite; }
@keyframes candidate-spin { to { transform: rotate(360deg); } }

:global(.dark) .deep-candidate-versions {
  --candidate-bg: #1f222a;
  --candidate-bg-soft: #1a1d24;
  --candidate-border: #363c48;
  --candidate-border-soft: #303641;
  --candidate-text: #e4e8ef;
  --candidate-muted: #9ba5b6;
}
:global(.dark) .candidate-section-icon,
:global(.dark) .candidate-card-icon { background: #302f55; }
:global(.dark) .candidate-portrait-launch { border-color: #44466d; background: linear-gradient(120deg, #282a3d, #242938); }
:global(.dark) .candidate-portrait-launch b { color: #e0e4ef; }
:global(.dark) .candidate-portrait-preview > article,
:global(.dark) .candidate-version-meta > span { border-color: #383e4b; background: #252932; }
:global(.dark) .candidate-portrait-preview b { color: #aaa8ff; }
:global(.dark) .candidate-portrait-preview p,
:global(.dark) .candidate-diff-list p { color: #b0b8c8; }
:global(.dark) .candidate-version-card.status-verified { background: #1d2924; }
:global(.dark) .candidate-diff-list > article { border-color: #383e4a; }

@media (max-width: 1080px) {
  .candidate-portrait-preview { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

@media (max-width: 720px) {
  .candidate-section-header { align-items: flex-start; flex-direction: column; }
  .candidate-section-summary { width: 100%; justify-content: space-between; }
  .candidate-card-header { align-items: flex-start; flex-wrap: wrap; }
  .candidate-card-header > div { flex-basis: calc(100% - 42px); }
  .candidate-status { margin-left: 39px; }
  .candidate-portrait-preview { grid-template-columns: 1fr; }
  .candidate-diff-list > article { grid-template-columns: 1fr; }
  .candidate-card-actions { align-items: stretch; flex-direction: column; }
  .candidate-card-actions button { width: 100%; }
}

@media (prefers-reduced-motion: reduce) {
  .candidate-portrait-launch svg { transition: none; }
}
</style>
